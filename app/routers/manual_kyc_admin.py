from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.manual_kyc import ManualKycAdminStatusUpdate, ManualKycResponse
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/manual-kyc", tags=["Admin", "Manual KYC"])

_TABLE = "manual_kyc"


def _row_or_404(manual_kyc_id: int) -> dict:
    result = supabase.table(_TABLE).select("*").eq("id", manual_kyc_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manual KYC not found",
        )
    return result.data[0]


@router.get("", response_model=List[ManualKycResponse])
def admin_list_all_manual_kyc(
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
    return [ManualKycResponse.model_validate(r) for r in (result.data or [])]


@router.get("/pending", response_model=List[ManualKycResponse])
def admin_list_pending_manual_kyc(
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
    return [ManualKycResponse.model_validate(r) for r in (result.data or [])]


@router.get("/user/{user_id}", response_model=ManualKycResponse)
def admin_get_manual_kyc_for_user(
    user_id: str,
    _: dict = Depends(require_role(["admin"])),
):
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
            detail="Manual KYC not found for this user",
        )
    return ManualKycResponse.model_validate(result.data[0])


@router.get("/{manual_kyc_id}", response_model=ManualKycResponse)
def admin_get_manual_kyc(
    manual_kyc_id: int,
    _: dict = Depends(require_role(["admin"])),
):
    return ManualKycResponse.model_validate(_row_or_404(manual_kyc_id))


@router.patch("/{manual_kyc_id}/status", response_model=ManualKycResponse)
def admin_update_manual_kyc_status(
    manual_kyc_id: int,
    payload: ManualKycAdminStatusUpdate,
    current_user: dict = Depends(require_role(["admin"])),
):
    _row_or_404(manual_kyc_id)
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
            .eq("id", manual_kyc_id)
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = (
                supabase.table(_TABLE).select("*").eq("id", manual_kyc_id).execute()
            )
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read manual KYC after update.",
            )
        return ManualKycResponse.model_validate(row)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.delete("/{manual_kyc_id}")
def admin_delete_manual_kyc(
    manual_kyc_id: int,
    _: dict = Depends(require_role(["admin"])),
):
    _row_or_404(manual_kyc_id)
    try:
        supabase.table(_TABLE).delete().eq("id", manual_kyc_id).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return {"message": "Manual KYC deleted", "manualKycId": manual_kyc_id}
