from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.investment import PaymentScheduleResponse, PaymentScheduleStatusPatch
from app.services.investment_actions import sync_investment_status_with_payment_lines
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/payment-schedules", tags=["Admin", "Payment schedules"])

_TABLE = "payment_schedules"


def _row_or_404(schedule_id: int) -> dict:
    result = supabase.table(_TABLE).select("*").eq("id", schedule_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment schedule line not found",
        )
    return result.data[0]


@router.patch("/{schedule_id}", response_model=PaymentScheduleResponse)
def admin_patch_payment_schedule_status(
    schedule_id: int,
    payload: PaymentScheduleStatusPatch,
    _: dict = Depends(require_role(["admin"])),
):
    _row_or_404(schedule_id)
    data = dump_update_or_400(payload)
    now = datetime.now(timezone.utc).isoformat()
    patch = {**data, "updatedAt": now}
    try:
        updated = (
            supabase.table(_TABLE)
            .update(patch)
            .eq("id", schedule_id)
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = supabase.table(_TABLE).select("*").eq("id", schedule_id).execute()
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read payment schedule after update.",
            )
        iid = str(row.get("investmentId") or "").strip()
        if iid:
            try:
                sync_investment_status_with_payment_lines(iid)
            except APIError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=format_api_error(e),
                ) from e
        return PaymentScheduleResponse.model_validate(row)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
