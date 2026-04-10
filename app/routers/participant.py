from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import bearer_scheme, require_role
from app.core.security import create_token, decode_token
from app.schemas.participant import ParticipantResponse, ParticipantUpdate
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.schedule_visit import (
    ScheduleVisitCreate,
    ScheduleVisitDeleteResponse,
    ScheduleVisitResponse,
)
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/participant", tags=["Participant"])

# ─── PUBLIC: Login ───────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
def participant_login(payload: LoginRequest):
    result = (
        supabase.table("participants")
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

    p = result.data[0]
    uid = str(p.get("participantId") or p.get("investorId") or "")
    token = create_token({
        "sub": p["phone"],
        "role": "participant",
        "userId": uid,
        "name": p["name"],
    })

    return TokenResponse(
        access_token=token,
        role="participant",
        userId=uid,
        name=p["name"],
    )


# ─── PROTECTED: Logout ──────────────────────────────────────────


@router.post("/logout")
def participant_logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    current_user: dict = Depends(require_role(["participant", "admin"])),
):
    token = credentials.credentials
    payload = decode_token(token)
    jti = payload.get("jti")

    existing = supabase.table("token_blacklist").select("id").eq("jti", jti).execute()
    if not existing.data:
        supabase.table("token_blacklist").insert({"jti": jti}).execute()

    return {"message": "Logged out successfully"}


# ─── PROTECTED: Profile ─────────────────────────────────────────


@router.get("/profile", response_model=ParticipantResponse)
def get_participant_profile(
    current_user: dict = Depends(require_role(["participant", "admin"])),
):
    result = (
        supabase.table("participants")
        .select("*")
        .eq("phone", current_user["sub"])
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Participant not found",
        )
    return result.data[0]


# ─── PROTECTED: Update profile (phone cannot be changed) ────────


@router.patch("/profile", response_model=ParticipantResponse)
def patch_participant_profile(
    payload: ParticipantUpdate,
    current_user: dict = Depends(require_role(["participant"])),
):
    data = dump_update_or_400(payload)
    try:
        updated = (
            supabase.table("participants")
            .update(data)
            .eq("phone", current_user["sub"])
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = (
                supabase.table("participants")
                .select("*")
                .eq("phone", current_user["sub"])
                .execute()
            )
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Participant not found",
            )
        return row
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.post(
    "/schedule-visits",
    response_model=ScheduleVisitResponse,
    status_code=status.HTTP_201_CREATED,
)
def participant_create_schedule_visit(
    payload: ScheduleVisitCreate,
    current_user: dict = Depends(require_role(["participant"])),
):
    if str(payload.userId).strip() != str(current_user.get("userId", "")).strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can create visits only for your own userId",
        )
    try:
        created = (
            supabase.table("schedule_visits")
            .insert(payload.model_dump())
            .execute()
        )
        if not created.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create schedule visit",
            )
        return created.data[0]
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.get("/schedule-visits", response_model=list[ScheduleVisitResponse])
def participant_get_schedule_visits(
    current_user: dict = Depends(require_role(["participant"])),
):
    try:
        result = (
            supabase.table("schedule_visits")
            .select("*")
            .eq("userId", str(current_user.get("userId", "")))
            .order("createdAt", desc=True)
            .execute()
        )
        return result.data or []
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.delete(
    "/schedule-visits/{visit_id}",
    response_model=ScheduleVisitDeleteResponse,
)
def participant_delete_schedule_visit(
    visit_id: int,
    current_user: dict = Depends(require_role(["participant"])),
):
    try:
        existing = (
            supabase.table("schedule_visits")
            .select("id,userId")
            .eq("id", visit_id)
            .execute()
        )
        if not existing.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Schedule visit not found",
            )
        if str(existing.data[0].get("userId", "")).strip() != str(current_user.get("userId", "")).strip():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can delete only your own schedule visits",
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
