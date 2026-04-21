from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.investment import (
    InvestmentAdminCreate,
    InvestmentAdminUpdate,
    InvestmentResponse,
    InvestmentStatusUpdate,
    PaymentScheduleResponse,
)
from app.utils.investment_id import new_investment_id
from app.services.investment_actions import replace_payment_schedules
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/investments", tags=["Admin", "Investments"])

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


@router.get("", response_model=List[InvestmentResponse])
def admin_list_investments(
    participant_id: Optional[str] = Query(None, description="Filter by participant id"),
    _: dict = Depends(require_role(["admin"])),
):
    try:
        q = supabase.table(_TABLE).select("*").order("createdAt", desc=True)
        if participant_id is not None and str(participant_id).strip():
            q = q.eq("participantId", str(participant_id).strip())
        result = q.execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [InvestmentResponse.model_validate(r) for r in (result.data or [])]


@router.post("", response_model=InvestmentResponse, status_code=status.HTTP_201_CREATED)
def admin_create_investment(
    payload: InvestmentAdminCreate,
    _: dict = Depends(require_role(["admin"])),
):
    iid = new_investment_id()
    inv_date = payload.investmentDate or datetime.now(timezone.utc)
    body = {
        "investmentId": iid,
        "participantId": payload.participantId.strip(),
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
        "status": payload.status,
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


@router.get("/{investment_id}/payment-schedules", response_model=List[PaymentScheduleResponse])
def admin_list_payment_schedules(
    investment_id: str,
    _: dict = Depends(require_role(["admin"])),
):
    _row_inv_or_404(investment_id)
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
def admin_get_investment(
    investment_id: str,
    _: dict = Depends(require_role(["admin"])),
):
    return InvestmentResponse.model_validate(_row_inv_or_404(investment_id))


@router.patch("/{investment_id}", response_model=InvestmentResponse)
def admin_patch_investment(
    investment_id: str,
    payload: InvestmentAdminUpdate,
    _: dict = Depends(require_role(["admin"])),
):
    _row_inv_or_404(investment_id)
    data = dump_update_or_400(payload)
    flat = {}
    for k, v in data.items():
        if v is None:
            continue
        if isinstance(v, datetime):
            flat[k] = v.isoformat()
        elif k in ("investedAmount", "roiPercentage", "monthlyPayout"):
            flat[k] = float(v)
        elif k == "durationMonths":
            flat[k] = int(v)
        else:
            flat[k] = v
    now = datetime.now(timezone.utc).isoformat()
    flat["updatedAt"] = now
    try:
        updated = (
            supabase.table(_TABLE)
            .update(flat)
            .eq("investmentId", investment_id)
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = (
                supabase.table(_TABLE).select("*").eq("investmentId", investment_id).execute()
            )
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read investment after update.",
            )
        return InvestmentResponse.model_validate(row)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.patch("/{investment_id}/status", response_model=InvestmentResponse)
def admin_patch_investment_status(
    investment_id: str,
    payload: InvestmentStatusUpdate,
    _: dict = Depends(require_role(["admin"])),
):
    row = _row_inv_or_404(investment_id)
    old_status = row.get("status")
    new_status = payload.status
    now = datetime.now(timezone.utc).isoformat()

    start = payload.investmentStartDate
    if new_status == "Active":
        if start is None:
            start = datetime.now(timezone.utc)
        elif start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        patch = {
            "status": new_status,
            "investmentStartDate": start.isoformat(),
            "updatedAt": now,
        }
        merged = dict(row)
        merged["monthlyPayout"] = float(merged.get("monthlyPayout") or 0)
        merged["durationMonths"] = int(merged.get("durationMonths") or 0)
        try:
            next_iso = replace_payment_schedules(investment_id, merged, start)
            patch["nextPayoutDate"] = next_iso
        except APIError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=format_api_error(e),
            ) from e
    else:
        patch = {"status": new_status, "updatedAt": now}
        if (
            str(old_status or "").strip() == "Active"
            and str(new_status or "").strip() in ("Processing", "Pending Approval")
        ):
            try:
                supabase.table(_PS).delete().eq("investmentId", investment_id).execute()
            except APIError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=format_api_error(e),
                ) from e
            patch["nextPayoutDate"] = None

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


@router.delete("/{investment_id}")
def admin_delete_investment(
    investment_id: str,
    _: dict = Depends(require_role(["admin"])),
):
    _row_inv_or_404(investment_id)
    try:
        supabase.table(_TABLE).delete().eq("investmentId", investment_id).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return {"message": "Investment deleted", "investmentId": investment_id}
