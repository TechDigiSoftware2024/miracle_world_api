from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.investment import (
    InvestmentDocUpdate,
    InvestmentParticipantCreate,
    InvestmentResponse,
    PaymentScheduleResponse,
)
from app.utils.investment_id import new_investment_id
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/investments", tags=["Participant", "Investments"])

_TABLE = "investments"
_PS = "payment_schedules"


def _row_inv_or_404(investment_id: str) -> dict:
    result = supabase.table(_TABLE).select("*").eq("investmentId", investment_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Investment not found",
        )
    return result.data[0]


@router.post("", response_model=InvestmentResponse, status_code=status.HTTP_201_CREATED)
def participant_create_investment(
    payload: InvestmentParticipantCreate,
    current_user: dict = Depends(require_role(["participant"])),
):
    pid = str(current_user.get("userId", "")).strip()
    if not pid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token is missing userId",
        )
    iid = new_investment_id()
    inv_date = payload.investmentDate or datetime.now(timezone.utc)
    body = {
        "investmentId": iid,
        "participantId": pid,
        "agentId": payload.agentId,
        "fundId": payload.fundId,
        "fundName": payload.fundName,
        "investedAmount": float(payload.investedAmount),
        "roiPercentage": float(payload.roiPercentage),
        "durationMonths": int(payload.durationMonths),
        "investmentDate": inv_date.isoformat() if isinstance(inv_date, datetime) else inv_date,
        "nextPayoutDate": None,
        "monthlyPayout": float(payload.monthlyPayout or 0),
        "isProfitCapitalPerMonth": payload.isProfitCapitalPerMonth,
        "status": "Processing",
        "investmentStartDate": None,
        "investmentDoc": "",
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
        refetch = supabase.table(_TABLE).select("*").eq("investmentId", iid).execute()
        row = refetch.data[0] if refetch.data else None
    if not row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read investment after insert.",
        )
    return InvestmentResponse.model_validate(row)


@router.get("", response_model=List[InvestmentResponse])
def participant_list_investments(
    current_user: dict = Depends(require_role(["participant"])),
):
    pid = str(current_user.get("userId", "")).strip()
    try:
        result = (
            supabase.table(_TABLE)
            .select("*")
            .eq("participantId", pid)
            .order("createdAt", desc=True)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [InvestmentResponse.model_validate(r) for r in (result.data or [])]


@router.get("/{investment_id}/payment-schedules", response_model=List[PaymentScheduleResponse])
def participant_list_payment_schedules(
    investment_id: str,
    current_user: dict = Depends(require_role(["participant"])),
):
    row = _row_inv_or_404(investment_id)
    if str(row.get("participantId", "")).strip() != str(current_user.get("userId", "")).strip():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your investment")
    try:
        result = (
            supabase.table(_PS)
            .select("*")
            .eq("investmentId", investment_id)
            .order("monthNumber")
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [PaymentScheduleResponse.model_validate(r) for r in (result.data or [])]


@router.get("/{investment_id}", response_model=InvestmentResponse)
def participant_get_investment(
    investment_id: str,
    current_user: dict = Depends(require_role(["participant"])),
):
    row = _row_inv_or_404(investment_id)
    if str(row.get("participantId", "")).strip() != str(current_user.get("userId", "")).strip():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your investment")
    return InvestmentResponse.model_validate(row)


@router.patch("/{investment_id}", response_model=InvestmentResponse)
def participant_patch_investment_doc(
    investment_id: str,
    payload: InvestmentDocUpdate,
    current_user: dict = Depends(require_role(["participant"])),
):
    row = _row_inv_or_404(investment_id)
    if str(row.get("participantId", "")).strip() != str(current_user.get("userId", "")).strip():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your investment")
    now = datetime.now(timezone.utc).isoformat()
    patch: dict = {"investmentDoc": payload.investmentDoc, "updatedAt": now}
    if str(row.get("status", "")).strip() == "Processing":
        patch["status"] = "Pending Approval"
    try:
        updated = (
            supabase.table(_TABLE)
            .update(patch)
            .eq("investmentId", investment_id)
            .execute()
        )
        out = updated.data[0] if updated.data else None
        if not out:
            refetch = (
                supabase.table(_TABLE).select("*").eq("investmentId", investment_id).execute()
            )
            out = refetch.data[0] if refetch.data else None
        if not out:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read investment after update.",
            )
        return InvestmentResponse.model_validate(out)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
