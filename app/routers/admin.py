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
from app.schemas.participant import ParticipantResponse, ParticipantUpdate
from app.schemas.partner import PartnerResponse, PartnerUpdate
from app.schemas.contact import ContactQueryResponse
from app.schemas.app_settings import AppSettingsResponse, AppSettingsUpdate
from app.schemas.schedule_visit import ScheduleVisitDeleteResponse, ScheduleVisitResponse
from app.utils.id_generator import generate_participant_id, generate_partner_id
from app.utils.db_column_names import camel_participant_pk_column, camel_partner_pk_column
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error
from app.utils.app_settings_repo import fetch_app_settings_row
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


# ─── PROTECTED: Contact form submissions ─────────────────────────


@router.get("/contact-queries", response_model=List[ContactQueryResponse])
def admin_list_contact_queries(
    current_user: dict = Depends(require_role(["admin"])),
):
    result = (
        supabase.table("contact_queries")
        .select("*")
        .order("createdAt", desc=True)
        .execute()
    )
    return result.data


# ─── PROTECTED: App settings (company + default introducer IDs) ──


@router.get("/settings", response_model=AppSettingsResponse)
def admin_get_app_settings(
    current_user: dict = Depends(require_role(["admin"])),
):
    row = fetch_app_settings_row()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="app_settings row missing. Run supabase_app_settings_table.sql in Supabase.",
        )
    return AppSettingsResponse.model_validate(row)


@router.patch("/settings", response_model=AppSettingsResponse)
def admin_patch_app_settings(
    payload: AppSettingsUpdate,
    current_user: dict = Depends(require_role(["admin"])),
):
    if not fetch_app_settings_row():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="app_settings row missing. Run supabase_app_settings_table.sql in Supabase.",
        )
    data = dump_update_or_400(payload)
    now = datetime.now(timezone.utc).isoformat()
    patch = {**data, "updatedAt": now}
    try:
        updated = (
            supabase.table("app_settings")
            .update(patch)
            .eq("id", 1)
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = (
                supabase.table("app_settings")
                .select("*")
                .eq("id", 1)
                .limit(1)
                .execute()
            )
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read app_settings after update.",
            )
        return AppSettingsResponse.model_validate(row)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


# ─── PROTECTED: Participants & partners (list / delete / patch) ─


@router.get("/participants", response_model=List[ParticipantResponse])
def admin_list_participants(
    current_user: dict = Depends(require_role(["admin"])),
):
    pid = camel_participant_pk_column()
    result = supabase.table("participants").select("*").order(pid).execute()
    return result.data


@router.get("/partners", response_model=List[PartnerResponse])
def admin_list_partners(
    current_user: dict = Depends(require_role(["admin"])),
):
    prid = camel_partner_pk_column()
    result = supabase.table("partners").select("*").order(prid).execute()
    return result.data


@router.get("/schedule-visits", response_model=List[ScheduleVisitResponse])
def admin_list_schedule_visits(
    current_user: dict = Depends(require_role(["admin"])),
):
    result = (
        supabase.table("schedule_visits")
        .select("*")
        .order("createdAt", desc=True)
        .execute()
    )
    return result.data or []


@router.delete("/schedule-visits/{visit_id}", response_model=ScheduleVisitDeleteResponse)
def admin_delete_schedule_visit(
    visit_id: int,
    current_user: dict = Depends(require_role(["admin"])),
):
    try:
        existing = (
            supabase.table("schedule_visits")
            .select("id")
            .eq("id", visit_id)
            .execute()
        )
        if not existing.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Schedule visit not found",
            )
        supabase.table("schedule_visits").delete().eq("id", visit_id).execute()
        return ScheduleVisitDeleteResponse(message="Schedule visit deleted", id=visit_id)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.delete("/participants/{participantId}")
def admin_delete_participant(
    participantId: str,
    current_user: dict = Depends(require_role(["admin"])),
):
    try:
        pid = camel_participant_pk_column()
        existing = (
            supabase.table("participants")
            .select(pid)
            .eq(pid, participantId)
            .execute()
        )
        if not existing.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Participant not found",
            )
        supabase.table("participants").delete().eq(pid, participantId).execute()
        return {"message": "Participant deleted", "participantId": participantId}
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.delete("/partners/{partnerId}")
def admin_delete_partner(
    partnerId: str,
    current_user: dict = Depends(require_role(["admin"])),
):
    try:
        prid = camel_partner_pk_column()
        existing = (
            supabase.table("partners")
            .select(prid)
            .eq(prid, partnerId)
            .execute()
        )
        if not existing.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Partner not found",
            )
        supabase.table("partners").delete().eq(prid, partnerId).execute()
        return {"message": "Partner deleted", "partnerId": partnerId}
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.patch("/participants/{participantId}", response_model=ParticipantResponse)
def admin_patch_participant(
    participantId: str,
    payload: ParticipantUpdate,
    current_user: dict = Depends(require_role(["admin"])),
):
    data = dump_update_or_400(payload)
    try:
        pid = camel_participant_pk_column()
        existing = (
            supabase.table("participants")
            .select(pid)
            .eq(pid, participantId)
            .execute()
        )
        if not existing.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Participant not found",
            )
        updated = (
            supabase.table("participants")
            .update(data)
            .eq(pid, participantId)
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = (
                supabase.table("participants")
                .select("*")
                .eq(pid, participantId)
                .execute()
            )
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read participant after update.",
            )
        return row
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.patch("/partners/{partnerId}", response_model=PartnerResponse)
def admin_patch_partner(
    partnerId: str,
    payload: PartnerUpdate,
    current_user: dict = Depends(require_role(["admin"])),
):
    data = dump_update_or_400(payload)
    try:
        prid = camel_partner_pk_column()
        existing = (
            supabase.table("partners")
            .select(prid)
            .eq(prid, partnerId)
            .execute()
        )
        if not existing.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Partner not found",
            )
        updated = (
            supabase.table("partners")
            .update(data)
            .eq(prid, partnerId)
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = (
                supabase.table("partners")
                .select("*")
                .eq(prid, partnerId)
                .execute()
            )
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read partner after update.",
            )
        return row
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


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
            .select(k["p_participant"])
            .eq(k["p_participant"], introducer_id)
            .execute()
        )
        a_check = (
            supabase.table("partners")
            .select(k["a_partner"])
            .eq(k["a_partner"], introducer_id)
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
                .select(k["p_participant"])
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
                k["p_participant"]: generate_participant_id(id_column=k["p_participant"]),
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
                .select(k["a_partner"])
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
                k["a_partner"]: generate_partner_id(id_column=k["a_partner"]),
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
            detail=format_api_error(e),
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
            detail=format_api_error(e),
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
