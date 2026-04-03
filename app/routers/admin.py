import random
from typing import List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from postgrest.exceptions import APIError
from pydantic import ValidationError

from app.db.database import supabase
from app.dependencies.auth import bearer_scheme, require_role
from app.core.security import create_token, decode_token
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.admin import AdminResponse
from app.schemas.user_request import RequestResponse
from app.utils.id_generator import generate_investor_id, generate_agent_id
from app.utils.supabase_columns import (
    approve_keys,
    introducer_id_from_row,
    normalize_user_request_row,
    user_request_row_style,
)

router = APIRouter(prefix="/admin", tags=["Admin"])

# ─── PUBLIC: Login ───────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
def admin_login(payload: LoginRequest):
    result = (
        supabase.table("admins")
        .select("*")
        .eq("phone", payload.phone)
        .eq("mpin", payload.mpin)
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid phone or mpin",
        )

    admin = result.data[0]
    token = create_token({
        "sub": admin["phone"],
        "role": "admin",
        "userId": admin["adminId"],
        "name": admin["name"],
    })

    return TokenResponse(
        access_token=token,
        role="admin",
        userId=admin["adminId"],
        name=admin["name"],
    )


# ─── PROTECTED: Logout ──────────────────────────────────────────


@router.post("/logout")
def admin_logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    current_user: dict = Depends(require_role(["admin"])),
):
    token = credentials.credentials
    payload = decode_token(token)
    jti = payload.get("jti")

    existing = supabase.table("token_blacklist").select("id").eq("jti", jti).execute()
    if not existing.data:
        supabase.table("token_blacklist").insert({"jti": jti}).execute()

    return {"message": "Logged out successfully"}


# ─── PROTECTED: Admin Profile ────────────────────────────────────


@router.get("/profile", response_model=AdminResponse)
def get_admin_profile(
    current_user: dict = Depends(require_role(["admin"])),
):
    result = (
        supabase.table("admins")
        .select("*")
        .eq("phone", current_user["sub"])
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin not found",
        )
    return result.data[0]


# ─── PROTECTED: Get All Requests ─────────────────────────────────


@router.get("/requests", response_model=List[RequestResponse])
def get_all_requests(
    current_user: dict = Depends(require_role(["admin"])),
):
    result = supabase.table("user_requests").select("*").order("id").execute()
    return result.data


# ─── PROTECTED: Approve Request ──────────────────────────────────


@router.put("/request/{request_id}/approve", response_model=RequestResponse)
def approve_request(
    request_id: int,
    current_user: dict = Depends(require_role(["admin"])),
):
    try:
        result = supabase.table("user_requests").select("*").eq("id", request_id).execute()
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Request not found",
            )

        req = result.data[0]
        style = user_request_row_style(req)
        k = approve_keys(style)

        if req.get("status") != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Request already {req.get('status')}",
            )

        introducer_id = introducer_id_from_row(req)
        if not introducer_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request row is missing introducer ID",
            )

        phone = req.get("phone")
        name = req.get("name")
        if phone is None or str(phone).strip() == "":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request row is missing phone",
            )
        if name is None or str(name).strip() == "":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request row is missing name",
            )
        phone = str(phone).strip()
        name = str(name).strip()

        now = datetime.now(timezone.utc).isoformat()
        role = (req.get("role") or "").lower()

        p_check = (
            supabase.table("participants")
            .select("id")
            .eq(k["p_investor"], introducer_id)
            .execute()
        )
        a_check = (
            supabase.table("partners")
            .select("id")
            .eq(k["a_agent"], introducer_id)
            .execute()
        )
        introducer_is_participant = bool(p_check.data)
        introducer_is_partner = bool(a_check.data)

        def reject_request_row(message: str, detail: str) -> None:
            supabase.table("user_requests").update({
                k["ur_status"]: "rejected",
                k["ur_message"]: message,
                k["ur_updated"]: now,
            }).eq("id", request_id).execute()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

        if not introducer_is_participant and not introducer_is_partner:
            reject_request_row(
                "Rejected: Introducer ID does not exist",
                "Introducer ID not found. Request has been rejected.",
            )

        if role == "partner" and not introducer_is_partner:
            reject_request_row(
                "Rejected: Partner requests require a partner introducer (agent ID)",
                "For partner signup, introducer must be an existing partner agent ID. Request has been rejected.",
            )

        mpin = str(random.randint(100000, 999999))

        if role == "participant":
            phone_exists = (
                supabase.table("participants")
                .select("id")
                .eq(k["p_phone"], phone)
                .execute()
            )
            if phone_exists.data:
                supabase.table("user_requests").update({
                    k["ur_status"]: "rejected",
                    k["ur_message"]: "Rejected: Participant account already exists for this phone",
                    k["ur_updated"]: now,
                }).eq("id", request_id).execute()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Participant account already exists for this phone",
                )

            supabase.table("participants").insert({
                k["p_investor"]: generate_investor_id(id_column=k["p_investor"]),
                k["p_name"]: name,
                k["p_phone"]: phone,
                k["p_email"]: "",
                k["p_address"]: "",
                k["p_introducer"]: introducer_id,
                k["p_mpin"]: mpin,
                k["p_status"]: "active",
                k["p_total"]: 0.0,
            }).execute()

        elif role == "partner":
            phone_exists = (
                supabase.table("partners")
                .select("id")
                .eq(k["a_phone"], phone)
                .execute()
            )
            if phone_exists.data:
                supabase.table("user_requests").update({
                    k["ur_status"]: "rejected",
                    k["ur_message"]: "Rejected: Partner account already exists for this phone",
                    k["ur_updated"]: now,
                }).eq("id", request_id).execute()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Partner account already exists for this phone",
                )

            supabase.table("partners").insert({
                k["a_agent"]: generate_agent_id(id_column=k["a_agent"]),
                k["a_name"]: name,
                k["a_phone"]: phone,
                k["a_email"]: "",
                k["a_location"]: "",
                k["a_introducer"]: introducer_id,
                k["a_mpin"]: mpin,
                k["a_profile"]: "",
                k["a_status"]: "active",
                k["a_commission"]: 0.0,
                k["a_self_commission"]: 0.0,
                k["a_self_profit"]: 0.0,
                k["a_gen_profit"]: 0.0,
                k["a_deals"]: 0,
                k["a_team"]: 0,
            }).execute()

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid role. Must be 'participant' or 'partner'",
            )

        updated = (
            supabase.table("user_requests")
            .update({
                k["ur_status"]: "approved",
                k["ur_message"]: "Your request has been approved! Contact admin for mpin",
                k["ur_pin"]: mpin,
                k["ur_updated"]: now,
            })
            .eq("id", request_id)
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = supabase.table("user_requests").select("*").eq("id", request_id).execute()
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read request after approval.",
            )
        norm = normalize_user_request_row(row)
        if norm.get("introducerId") is None or norm.get("createdAt") is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Incomplete user_requests row returned from database.",
            )
        try:
            return RequestResponse.model_validate(norm)
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=e.errors(),
            ) from e

    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_format_api_error(e),
        ) from e
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.errors(),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{type(e).__name__}: {e}",
        ) from e


def _format_api_error(e: APIError) -> str:
    raw = e.args[0] if e.args else str(e)
    if isinstance(raw, dict):
        msg = raw.get("message") or str(raw)
        if raw.get("details"):
            msg = f"{msg} ({raw['details']})"
        return msg
    return str(raw)


# ─── PROTECTED: Reject Request ───────────────────────────────────


@router.put("/request/{request_id}/reject", response_model=RequestResponse)
def reject_request(
    request_id: int,
    current_user: dict = Depends(require_role(["admin"])),
):
    try:
        result = supabase.table("user_requests").select("*").eq("id", request_id).execute()
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Request not found",
            )

        req = result.data[0]
        k = approve_keys(user_request_row_style(req))

        if req.get("status") != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Request already {req.get('status')}",
            )

        now = datetime.now(timezone.utc).isoformat()
        updated = (
            supabase.table("user_requests")
            .update({
                k["ur_status"]: "rejected",
                k["ur_message"]: "Request rejected",
                k["ur_updated"]: now,
            })
            .eq("id", request_id)
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = supabase.table("user_requests").select("*").eq("id", request_id).execute()
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read request after reject.",
            )
        norm = normalize_user_request_row(row)
        if norm.get("introducerId") is None or norm.get("createdAt") is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Incomplete user_requests row returned from database.",
            )
        try:
            return RequestResponse.model_validate(norm)
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=e.errors(),
            ) from e

    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_format_api_error(e),
        ) from e
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.errors(),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{type(e).__name__}: {e}",
        ) from e
