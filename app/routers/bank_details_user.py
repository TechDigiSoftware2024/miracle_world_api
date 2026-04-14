from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.bank_details import BankDetailCreate, BankDetailResponse, BankDetailUserUpdate
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/bank-details", tags=["Bank details", "User"])

_TABLE = "bank_details"


def _assert_self_or_admin(user_id: str, current_user: dict) -> None:
    role = current_user.get("role")
    if role == "admin":
        return
    if str(current_user.get("userId", "")).strip() != str(user_id).strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can access bank details only for your own userId",
        )


def _row_or_404(bank_detail_id: int) -> dict:
    result = supabase.table(_TABLE).select("*").eq("id", bank_detail_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bank details not found",
        )
    return result.data[0]


@router.get("/user/{user_id}", response_model=BankDetailResponse)
def get_bank_details_for_user(
    user_id: str,
    current_user: dict = Depends(require_role(["participant", "partner", "admin"])),
):
    _assert_self_or_admin(user_id, current_user)
    try:
        result = (
            supabase.table(_TABLE).select("*").eq("userId", user_id).limit(1).execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bank details not found for this user",
        )
    return BankDetailResponse.model_validate(result.data[0])


@router.post("", response_model=BankDetailResponse, status_code=status.HTTP_201_CREATED)
def create_bank_details(
    payload: BankDetailCreate,
    current_user: dict = Depends(require_role(["participant", "partner"])),
):
    uid = str(current_user.get("userId", "")).strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token is missing userId",
        )
    existing = (
        supabase.table(_TABLE).select("id").eq("userId", uid).limit(1).execute()
    )
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bank details already exist for this user; use PUT to update",
        )
    body = {
        **payload.model_dump(),
        "userId": uid,
        "status": "Pending",
        "rejectionReason": None,
        "verifiedBy": None,
        "verifiedAt": None,
        "updatedAt": None,
    }
    try:
        inserted = supabase.table(_TABLE).insert(body).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    row = inserted.data[0] if inserted.data else None
    if not row:
        refetch = supabase.table(_TABLE).select("*").eq("userId", uid).execute()
        row = refetch.data[0] if refetch.data else None
    if not row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read bank details after insert.",
        )
    return BankDetailResponse.model_validate(row)


@router.put("/{bank_detail_id}", response_model=BankDetailResponse)
def update_bank_details(
    bank_detail_id: int,
    payload: BankDetailUserUpdate,
    current_user: dict = Depends(require_role(["participant", "partner"])),
):
    row = _row_or_404(bank_detail_id)
    uid = str(current_user.get("userId", "")).strip()
    if str(row.get("userId", "")).strip() != uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can update only your own bank details",
        )
    if row.get("status") == "Approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approved bank details cannot be edited",
        )
    data = dump_update_or_400(payload)
    now = datetime.now(timezone.utc).isoformat()
    patch = {**data, "updatedAt": now}
    if row.get("status") == "Rejected":
        patch["status"] = "Pending"
        patch["rejectionReason"] = None
        patch["verifiedBy"] = None
        patch["verifiedAt"] = None
    try:
        updated = (
            supabase.table(_TABLE)
            .update(patch)
            .eq("id", bank_detail_id)
            .execute()
        )
        out = updated.data[0] if updated.data else None
        if not out:
            refetch = (
                supabase.table(_TABLE).select("*").eq("id", bank_detail_id).execute()
            )
            out = refetch.data[0] if refetch.data else None
        if not out:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read bank details after update.",
            )
        return BankDetailResponse.model_validate(out)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
