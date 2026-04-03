from typing import List

from fastapi import APIRouter, HTTPException, status

from app.db.database import supabase
from app.schemas.user_request import RequestCreate, RequestResponse, TrackResponse
from app.schemas.auth import AdminPhoneCheckRequest, AdminPhoneCheckResponse

router = APIRouter(tags=["Public"])


@router.post("/check-admin-phone", response_model=AdminPhoneCheckResponse)
def check_admin_phone(payload: AdminPhoneCheckRequest):
    phone = payload.phone.strip()
    if not phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone is required",
        )
    result = supabase.table("admins").select("id").eq("phone", phone).execute()
    return AdminPhoneCheckResponse(is_admin=bool(result.data))


@router.post("/request", response_model=RequestResponse, status_code=status.HTTP_201_CREATED)
def create_request(payload: RequestCreate):
    role = payload.role.lower()
    if role not in ("participant", "partner"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be 'participant' or 'partner'",
        )

    existing = (
        supabase.table("user_requests")
        .select("id")
        .eq("phone", payload.phone)
        .eq("role", role)
        .execute()
    )
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request already exists for this phone with role '{role}'",
        )

    result = (
        supabase.table("user_requests")
        .insert({
            "phone": payload.phone,
            "role": role,
            "name": payload.name,
            "introducerId": payload.introducerId,
            "status": "pending",
        })
        .execute()
    )
    return result.data[0]


@router.get("/track-request/{phone}", response_model=List[TrackResponse])
def track_request(phone: str):
    result = (
        supabase.table("user_requests")
        .select("*")
        .eq("phone", phone)
        .order("id")
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No request found",
        )
    return result.data
