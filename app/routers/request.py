from typing import List

from fastapi import APIRouter, HTTPException, Query, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.schemas.user_request import (
    RequestCreate,
    RequestResponse,
    TrackResponse,
    UserRequestDeleteResponse,
)
from app.schemas.auth import AdminPhoneCheckRequest, AdminPhoneCheckResponse
from app.utils.phone_normalize import normalize_phone_digits
from app.utils.supabase_errors import format_api_error

router = APIRouter(tags=["Public"])


@router.post("/check-admin-phone", response_model=AdminPhoneCheckResponse)
def check_admin_phone(payload: AdminPhoneCheckRequest):
    phone = payload.phone.strip()
    if not phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone is required",
        )
    result = supabase.table("admins").select("adminId").eq("phone", phone).execute()
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


@router.delete(
    "/request/{request_id}",
    response_model=UserRequestDeleteResponse,
)
def delete_user_request(
    request_id: int,
    phone: str = Query(
        ...,
        description="Must match the phone on this request (same as used when submitting).",
    ),
):
    """
    Public: remove a signup request by id. **phone** must match the stored row (reduces blind deletes).
    Use **id** from `GET /track-request/{phone}`.
    """
    if not phone.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="phone query parameter is required",
        )
    try:
        existing = (
            supabase.table("user_requests")
            .select("id", "phone")
            .eq("id", request_id)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e

    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        )

    row_phone = existing.data[0].get("phone") or ""
    if normalize_phone_digits(row_phone) != normalize_phone_digits(phone):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        )

    try:
        supabase.table("user_requests").delete().eq("id", request_id).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e

    return UserRequestDeleteResponse(message="Request deleted", id=request_id)


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
