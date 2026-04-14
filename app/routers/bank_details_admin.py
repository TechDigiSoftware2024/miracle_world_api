from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.bank_details import (
    BankDetailAdminStatusUpdate,
    BankDetailResponse,
)
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/bank-details", tags=["Admin", "Bank details"])

_TABLE = "bank_details"


def _row_or_404(bank_detail_id: int) -> dict:
    result = supabase.table(_TABLE).select("*").eq("id", bank_detail_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bank details not found",
        )
    return result.data[0]


@router.get("/pending", response_model=List[BankDetailResponse])
def admin_list_pending_bank_details(
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
    return [BankDetailResponse.model_validate(r) for r in (result.data or [])]


@router.get("/{bank_detail_id}", response_model=BankDetailResponse)
def admin_get_bank_details(
    bank_detail_id: int,
    _: dict = Depends(require_role(["admin"])),
):
    return BankDetailResponse.model_validate(_row_or_404(bank_detail_id))


@router.patch("/{bank_detail_id}/status", response_model=BankDetailResponse)
def admin_update_bank_details_status(
    bank_detail_id: int,
    payload: BankDetailAdminStatusUpdate,
    current_user: dict = Depends(require_role(["admin"])),
):
    _row_or_404(bank_detail_id)
    data = dump_update_or_400(payload)
    new_status = data["status"]
    now = datetime.now(timezone.utc).isoformat()
    admin_id = str(current_user.get("userId", "")).strip()

    patch: dict = {"status": new_status, "updatedAt": now}
    if new_status in ("Approved", "Rejected"):
        patch["verifiedBy"] = admin_id or None
        patch["verifiedAt"] = now
        if new_status == "Approved":
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
            .eq("id", bank_detail_id)
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = (
                supabase.table(_TABLE).select("*").eq("id", bank_detail_id).execute()
            )
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read bank details after update.",
            )
        return BankDetailResponse.model_validate(row)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
