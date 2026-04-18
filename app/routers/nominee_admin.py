from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.nominee import NomineeAdminStatusUpdate, NomineeResponse
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/nominees", tags=["Admin", "Nominees"])

_TABLE = "nominees"


def _row_or_404(nominee_id: int) -> dict:
    result = supabase.table(_TABLE).select("*").eq("id", nominee_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nominee not found",
        )
    return result.data[0]


@router.get("", response_model=List[NomineeResponse])
def admin_list_all_nominees(
    _: dict = Depends(require_role(["admin"])),
):
    try:
        result = (
            supabase.table(_TABLE)
            .select("*")
            .order("createdAt", desc=True)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [NomineeResponse.model_validate(r) for r in (result.data or [])]


@router.get("/pending", response_model=List[NomineeResponse])
def admin_list_pending_nominees(
    _: dict = Depends(require_role(["admin"])),
):
    try:
        result = (
            supabase.table(_TABLE)
            .select("*")
            .eq("status", "Pending")
            .order("createdAt", desc=True)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [NomineeResponse.model_validate(r) for r in (result.data or [])]


@router.get("/user/{user_id}", response_model=List[NomineeResponse])
def admin_list_nominees_for_user(
    user_id: str,
    _: dict = Depends(require_role(["admin"])),
):
    try:
        result = (
            supabase.table(_TABLE)
            .select("*")
            .eq("userId", user_id)
            .order("createdAt", desc=True)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [NomineeResponse.model_validate(r) for r in (result.data or [])]


@router.get("/{nominee_id}", response_model=NomineeResponse)
def admin_get_nominee(
    nominee_id: int,
    _: dict = Depends(require_role(["admin"])),
):
    return NomineeResponse.model_validate(_row_or_404(nominee_id))


@router.patch("/{nominee_id}/status", response_model=NomineeResponse)
def admin_update_nominee_status(
    nominee_id: int,
    payload: NomineeAdminStatusUpdate,
    current_user: dict = Depends(require_role(["admin"])),
):
    _row_or_404(nominee_id)
    data = dump_update_or_400(payload)
    new_status = data["status"]
    now = datetime.now(timezone.utc).isoformat()
    admin_id = str(current_user.get("userId", "")).strip()

    patch: dict = {"status": new_status, "updatedAt": now}
    if new_status in ("Verified", "Rejected"):
        patch["verifiedBy"] = admin_id or None
        patch["verifiedAt"] = now
        if new_status == "Verified":
            patch["rejectionReason"] = None
        else:
            if "rejectionReason" in data:
                patch["rejectionReason"] = data.get("rejectionReason")
    else:
        patch["verifiedBy"] = None
        patch["verifiedAt"] = None
        patch["rejectionReason"] = None

    try:
        updated = (
            supabase.table(_TABLE)
            .update(patch)
            .eq("id", nominee_id)
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = (
                supabase.table(_TABLE).select("*").eq("id", nominee_id).execute()
            )
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read nominee after update.",
            )
        return NomineeResponse.model_validate(row)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.delete("/{nominee_id}")
def admin_delete_nominee(
    nominee_id: int,
    _: dict = Depends(require_role(["admin"])),
):
    _row_or_404(nominee_id)
    try:
        supabase.table(_TABLE).delete().eq("id", nominee_id).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return {"message": "Nominee deleted", "nomineeId": nominee_id}
