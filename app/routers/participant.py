from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import bearer_scheme, require_role
from app.core.security import create_token, decode_token
from app.schemas.participant import (
    ParticipantProfilePatch,
    ParticipantResponse,
    PartnerSearchResponse,
)
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.fund_type import FundTypeResponse
from app.schemas.schedule_visit import (
    ScheduleVisitCreate,
    ScheduleVisitDeleteResponse,
    ScheduleVisitResponse,
)
from app.utils.db_column_names import camel_partner_pk_column
from app.utils.patch_payload import dump_update_or_400
from app.utils.participant_fund_types import (
    enrich_participant_row_with_special_fund_ids,
    fetch_visible_fund_type_rows,
)
from app.utils.phone_normalize import is_plausible_in_mobile, normalize_phone_digits
from app.utils.file_uploads import save_upload_file
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
    uid = str(current_user.get("userId", "")).strip()
    row = enrich_participant_row_with_special_fund_ids(dict(result.data[0]), uid)
    return ParticipantResponse.model_validate(row)


# ─── PROTECTED: Update profile (phone cannot be changed) ────────


@router.patch("/profile", response_model=ParticipantResponse)
def patch_participant_profile(
    payload: ParticipantProfilePatch,
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
        uid = str(current_user.get("userId", "")).strip()
        return ParticipantResponse.model_validate(
            enrich_participant_row_with_special_fund_ids(row, uid)
        )
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.post("/profile-image/upload", response_model=ParticipantResponse)
def upload_participant_profile_image(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_role(["participant"])),
):
    stored_path = save_upload_file(file, "profile_images")
    try:
        updated = (
            supabase.table("participants")
            .update({"profileImage": stored_path})
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
        uid = str(current_user.get("userId", "")).strip()
        return ParticipantResponse.model_validate(
            enrich_participant_row_with_special_fund_ids(row, uid)
        )
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.get("/partners/search", response_model=PartnerSearchResponse)
def participant_search_partner(
    name: Optional[str] = Query(None, max_length=200),
    partnerId: Optional[str] = Query(None, max_length=50),
    phone: Optional[str] = Query(None, max_length=20),
    current_user: dict = Depends(require_role(["participant"])),
):
    """
    Find a single partner by exactly one of: **name** (partial, case-insensitive),
    **partnerId** (exact), or **phone** (digits normalized to 10-digit India style).
    """
    n = (name or "").strip()
    pid = (partnerId or "").strip()
    ph = (phone or "").strip()
    filled = sum(bool(x) for x in (n, pid, ph))
    if filled != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide exactly one of: name, partnerId, or phone",
        )

    prid = camel_partner_pk_column()
    select_cols = f"{prid},name,phone"

    try:
        if pid:
            result = (
                supabase.table("partners")
                .select(select_cols)
                .eq(prid, pid)
                .limit(1)
                .execute()
            )
        elif ph:
            digits = normalize_phone_digits(ph)
            if not is_plausible_in_mobile(ph):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="phone must be a plausible 10-digit mobile number",
                )
            result = (
                supabase.table("partners")
                .select(select_cols)
                .eq("phone", digits)
                .limit(1)
                .execute()
            )
        else:
            safe = "".join(c for c in n if c not in "%_\\")
            if not safe.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="name must contain at least one valid character",
                )
            pattern = f"%{safe.strip()}%"
            result = (
                supabase.table("partners")
                .select(select_cols)
                .ilike("name", pattern)
                .order(prid)
                .limit(1)
                .execute()
            )
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No partner found",
        )
    return PartnerSearchResponse.model_validate(result.data[0])


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


@router.get(
    "/fund-types",
    response_model=List[FundTypeResponse],
    summary="List fund types for the logged-in participant",
)
def participant_list_fund_types(
    current_user: dict = Depends(require_role(["participant"])),
):
    """
    Returns **active** fund types: always non-special funds, plus **special** funds this participant
    is assigned when **`isEligible`** is true. Use this instead of public `GET /fund-types` in the
    participant app so restricted funds stay hidden.
    """
    uid = str(current_user.get("userId", "")).strip()
    raw_rows = fetch_visible_fund_type_rows(uid)
    return [FundTypeResponse.model_validate(row) for row in raw_rows]
