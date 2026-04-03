import random
from typing import List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app.db.database import supabase
from app.dependencies.auth import bearer_scheme, require_role
from app.core.security import create_token, decode_token
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.admin import AdminResponse
from app.schemas.user_request import RequestResponse
from app.utils.id_generator import generate_investor_id, generate_agent_id

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
    result = supabase.table("user_requests").select("*").eq("id", request_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        )

    req = result.data[0]

    if req["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request already {req['status']}",
        )

    introducer_id = req["introducerId"]
    now = datetime.now(timezone.utc).isoformat()

    p_check = supabase.table("participants").select("id").eq("investorId", introducer_id).execute()
    a_check = supabase.table("partners").select("id").eq("agentId", introducer_id).execute()

    if not p_check.data and not a_check.data:
        supabase.table("user_requests").update({
            "status": "rejected",
            "message": "Rejected: Introducer ID does not exist",
            "updatedAt": now,
        }).eq("id", request_id).execute()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Introducer ID not found in participants or partners. Request has been rejected.",
        )

    mpin = str(random.randint(100000, 999999))
    role = req["role"].lower()

    if role == "participant":
        phone_exists = supabase.table("participants").select("id").eq("phone", req["phone"]).execute()
        if phone_exists.data:
            supabase.table("user_requests").update({
                "status": "rejected",
                "message": "Rejected: Participant account already exists for this phone",
                "updatedAt": now,
            }).eq("id", request_id).execute()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Participant account already exists for this phone",
            )

        supabase.table("participants").insert({
            "investorId": generate_investor_id(),
            "name": req["name"],
            "phone": req["phone"],
            "introducer": introducer_id,
            "mpin": mpin,
        }).execute()

    elif role == "partner":
        phone_exists = supabase.table("partners").select("id").eq("phone", req["phone"]).execute()
        if phone_exists.data:
            supabase.table("user_requests").update({
                "status": "rejected",
                "message": "Rejected: Partner account already exists for this phone",
                "updatedAt": now,
            }).eq("id", request_id).execute()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Partner account already exists for this phone",
            )

        supabase.table("partners").insert({
            "agentId": generate_agent_id(),
            "name": req["name"],
            "phone": req["phone"],
            "introducer": introducer_id,
            "mpin": mpin,
        }).execute()

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role. Must be 'participant' or 'partner'",
        )

    updated = supabase.table("user_requests").update({
        "status": "approved",
        "message": "Your request has been approved! Contact admin for mpin",
        "pin": mpin,
        "updatedAt": now,
    }).eq("id", request_id).execute()

    return updated.data[0]


# ─── PROTECTED: Reject Request ───────────────────────────────────


@router.put("/request/{request_id}/reject", response_model=RequestResponse)
def reject_request(
    request_id: int,
    current_user: dict = Depends(require_role(["admin"])),
):
    result = supabase.table("user_requests").select("*").eq("id", request_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        )

    req = result.data[0]

    if req["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request already {req['status']}",
        )

    now = datetime.now(timezone.utc).isoformat()
    updated = supabase.table("user_requests").update({
        "status": "rejected",
        "message": "Request rejected",
        "updatedAt": now,
    }).eq("id", request_id).execute()

    return updated.data[0]
