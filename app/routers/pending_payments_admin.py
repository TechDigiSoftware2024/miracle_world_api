from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.pending_payments_admin import (
    GeneratePayoutsRequest,
    GeneratePayoutsResponse,
    MarkPaidItemResult,
    MarkPaidRequest,
    MarkPaidResponse,
    PendingPaymentsListResponse,
)
from app.services.partner_portfolio_recalc import recalculate_partner_portfolio
from app.services.participant_portfolio_recalc import recalculate_participant_portfolio
from app.services.pending_payments_query import query_pending_payments_rollup
from app.services.schedule_payout_workflow import (
    mark_partner_commission_schedules_paid,
    mark_payment_schedule_paid,
)
from app.utils.payout_id import new_payout_id
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/pending-payments", tags=["Admin", "Pending payments"])


def _dt_for_payout(val) -> datetime:
    if isinstance(val, datetime):
        d = val
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    s = str(val).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        d = datetime.now(timezone.utc)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _partner_commission_audit_payout_exists(commission_schedule_id: int, user_id: str) -> bool:
    """True if a partner payout row already references this commission line (idempotency)."""
    cid = int(commission_schedule_id)
    uid = str(user_id or "").strip()
    if not uid:
        return True
    needle = f"commissionScheduleId={cid} investmentId"
    try:
        res = (
            supabase.table("payouts")
            .select("payoutId")
            .eq("userId", uid)
            .eq("recipientType", "partner")
            .ilike("remarks", f"%{needle}%")
            .limit(1)
            .execute()
        )
    except APIError:
        return False
    return bool(res.data)


def _insert_payout_row(
    *,
    user_id: str,
    recipient_type: str,
    amount: float,
    investment_id: Optional[str],
    payout_date: datetime,
    payout_type: str,
    payout_status: str,
    payment_method: str,
    transaction_id: Optional[str],
    remarks: str,
    level_depth: Optional[int],
    admin_id: str,
) -> str:
    pid = new_payout_id()
    pd = payout_date if payout_date.tzinfo else payout_date.replace(tzinfo=timezone.utc)
    body = {
        "payoutId": pid,
        "userId": str(user_id).strip(),
        "recipientType": recipient_type,
        "amount": round(float(amount), 2),
        "status": payout_status,
        "paymentMethod": payment_method,
        "transactionId": transaction_id,
        "investmentId": str(investment_id).strip() if investment_id else None,
        "payoutDate": pd.isoformat(),
        "remarks": remarks or "",
        "payoutType": payout_type,
        "createdBy": "automatic",
        "createdByAdminId": (str(admin_id).strip() if admin_id else None),
        "levelDepth": level_depth,
        "updatedAt": None,
    }
    if recipient_type == "participant":
        body["levelDepth"] = None
    try:
        supabase.table("payouts").insert(body).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return pid


@router.get("", response_model=PendingPaymentsListResponse)
def admin_list_pending_payment_rollups(
    recipient_type: str = Query(
        "all",
        description="all | participant | partner",
        alias="recipientType",
    ),
    investment_status: str = Query(
        "Active",
        description="Active (default) or all",
        alias="investmentStatus",
    ),
    payout_date: Optional[str] = Query(
        None,
        description="Exact calendar date YYYY-MM-DD (UTC date portion match on payoutDate)",
        alias="payoutDate",
    ),
    payout_date_from: Optional[str] = Query(None, alias="payoutDateFrom"),
    payout_date_to: Optional[str] = Query(None, alias="payoutDateTo"),
    month_number: Optional[int] = Query(None, alias="monthNumber", ge=1),
    user_id_query: Optional[str] = Query(
        None,
        description="Case-insensitive substring on participantId or beneficiaryPartnerId",
        alias="userId",
    ),
    name_query: Optional[str] = Query(
        None,
        description="Case-insensitive substring on participant or partner name",
        alias="name",
    ),
    group_partner_by: str = Query(
        "auto",
        description="auto | beneficiary | month — partner row collapsing (matches Flutter date-group rule when auto)",
        alias="groupPartnerBy",
    ),
    _: dict = Depends(require_role(["admin"])),
):
    try:
        return query_pending_payments_rollup(
            recipient_type=recipient_type,
            investment_status=investment_status,
            exact_date=payout_date,
            date_from=payout_date_from,
            date_to=payout_date_to,
            month_number=month_number,
            user_id_query=user_id_query,
            name_query=name_query,
            group_partner_by=group_partner_by,
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.post("/mark-paid", response_model=MarkPaidResponse)
def admin_mark_schedules_paid(
    payload: MarkPaidRequest,
    current_user: dict = Depends(require_role(["admin"])),
):
    """Mark participant payment_schedules and/or partner_commission_schedules as paid; optional payout audit rows.

    Partner ``recordPayouts``: creates one **paid** ``payouts`` row per **requested** commission id whose line is
    **paid** (including lines already paid via participant schedule sync), unless an audit row already exists
    for that ``commissionScheduleId`` (``remarks`` contains ``commissionScheduleId={id} investmentId``).
    """
    if not payload.participant_schedule_ids and not payload.partner_commission_schedule_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide participantScheduleIds and/or partnerCommissionScheduleIds",
        )
    admin_id = str(current_user.get("userId", "") or "").strip()
    results: List[MarkPaidItemResult] = []
    payouts_recorded = 0

    for psid in payload.participant_schedule_ids:
        try:
            row = mark_payment_schedule_paid(int(psid))
            results.append(
                MarkPaidItemResult(ref=str(psid), kind="participant", ok=True, detail=None)
            )
            if payload.record_payouts:
                iid = str(row.get("investmentId") or "").strip()
                inv_r = (
                    supabase.table("investments")
                    .select("participantId")
                    .eq("investmentId", iid)
                    .limit(1)
                    .execute()
                )
                uid = ""
                if inv_r.data:
                    uid = str(inv_r.data[0].get("participantId") or "").strip()
                if uid:
                    rmk = payload.remarks or ""
                    rmk = f"{rmk} scheduleId={psid} investmentId={iid}".strip()
                    _insert_payout_row(
                        user_id=uid,
                        recipient_type="participant",
                        amount=float(row.get("amount") or 0),
                        investment_id=iid,
                        payout_date=_dt_for_payout(row.get("payoutDate")),
                        payout_type="monthly_income",
                        payout_status="paid",
                        payment_method=payload.payment_method,
                        transaction_id=payload.transaction_id,
                        remarks=rmk,
                        level_depth=None,
                        admin_id=admin_id,
                    )
                    payouts_recorded += 1
                    recalculate_participant_portfolio(uid)
        except ValueError as e:
            results.append(
                MarkPaidItemResult(
                    ref=str(psid),
                    kind="participant",
                    ok=False,
                    detail=str(e),
                )
            )

    pids = sorted({int(x) for x in payload.partner_commission_schedule_ids if x is not None})
    if pids:
        ref = ",".join(str(i) for i in pids)
        try:
            mark_partner_commission_schedules_paid(pids)
            results.append(
                MarkPaidItemResult(ref=ref, kind="partner", ok=True, detail=None)
            )
            if payload.record_payouts:
                fetched = (
                    supabase.table("partner_commission_schedules")
                    .select("*")
                    .in_("id", pids)
                    .execute()
                )
                seen_recalc: set[str] = set()
                for r in fetched.data or []:
                    if str(r.get("status") or "").strip().lower() != "paid":
                        continue
                    cid = int(r["id"])
                    uid = str(r.get("beneficiaryPartnerId") or "").strip()
                    if not uid:
                        continue
                    if _partner_commission_audit_payout_exists(cid, uid):
                        continue
                    ld = int(r.get("level") or 0)
                    level_depth = ld if ld >= 1 else None
                    iid = str(r.get("investmentId") or "").strip()
                    amt = float(r.get("amount") or 0)
                    rmk = payload.remarks or ""
                    rmk = f"{rmk} commissionScheduleId={cid} investmentId={iid}".strip()
                    _insert_payout_row(
                        user_id=uid,
                        recipient_type="partner",
                        amount=amt,
                        investment_id=iid or None,
                        payout_date=_dt_for_payout(r.get("payoutDate")),
                        payout_type="commission",
                        payout_status="paid",
                        payment_method=payload.payment_method,
                        transaction_id=payload.transaction_id,
                        remarks=rmk,
                        level_depth=level_depth,
                        admin_id=admin_id,
                    )
                    payouts_recorded += 1
                    if uid not in seen_recalc:
                        seen_recalc.add(uid)
                        recalculate_partner_portfolio(uid)
        except ValueError as e:
            results.append(
                MarkPaidItemResult(ref=ref, kind="partner", ok=False, detail=str(e))
            )

    return MarkPaidResponse(results=results, payoutsRecorded=payouts_recorded)


@router.post("/generate-payouts", response_model=GeneratePayoutsResponse)
def admin_generate_payout_records_from_schedules(
    payload: GeneratePayoutsRequest,
    current_user: dict = Depends(require_role(["admin"])),
):
    """Insert **pending** `payouts` rows from schedule lines (does not mark schedules paid)."""
    if not payload.participant_schedule_ids and not payload.partner_commission_schedule_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide participantScheduleIds and/or partnerCommissionScheduleIds",
        )
    admin_id = str(current_user.get("userId", "") or "").strip()
    created_ids: List[str] = []

    for psid in payload.participant_schedule_ids:
        sr = supabase.table("payment_schedules").select("*").eq("id", int(psid)).limit(1).execute()
        if not sr.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"payment schedule {psid} not found",
            )
        row = sr.data[0]
        st = str(row.get("status") or "").strip().lower()
        if st not in ("pending", "due"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"schedule {psid} is not pending/due",
            )
        iid = str(row.get("investmentId") or "").strip()
        ir = supabase.table("investments").select("participantId").eq("investmentId", iid).limit(1).execute()
        if not ir.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"investment {iid} not found",
            )
        uid = str(ir.data[0].get("participantId") or "").strip()
        rmk = payload.remarks or ""
        rmk = f"{rmk} generated from scheduleId={psid}".strip()
        pid = _insert_payout_row(
            user_id=uid,
            recipient_type="participant",
            amount=float(row.get("amount") or 0),
            investment_id=iid,
            payout_date=_dt_for_payout(row.get("payoutDate")),
            payout_type="monthly_income",
            payout_status="pending",
            payment_method=payload.payment_method,
            transaction_id=None,
            remarks=rmk,
            level_depth=None,
            admin_id=admin_id,
        )
        created_ids.append(pid)
        recalculate_participant_portfolio(uid)

    for cid in payload.partner_commission_schedule_ids:
        cr = (
            supabase.table("partner_commission_schedules")
            .select("*")
            .eq("id", int(cid))
            .limit(1)
            .execute()
        )
        if not cr.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"partner commission schedule {cid} not found",
            )
        row = cr.data[0]
        st = str(row.get("status") or "").strip().lower()
        if st not in ("pending", "due"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"commission line {cid} is not pending/due",
            )
        uid = str(row.get("beneficiaryPartnerId") or "").strip()
        iid = str(row.get("investmentId") or "").strip()
        ld = int(row.get("level") or 0)
        level_depth = ld if ld >= 1 else None
        rmk = payload.remarks or ""
        rmk = f"{rmk} generated from commissionScheduleId={cid}".strip()
        pid = _insert_payout_row(
            user_id=uid,
            recipient_type="partner",
            amount=float(row.get("amount") or 0),
            investment_id=iid or None,
            payout_date=_dt_for_payout(row.get("payoutDate")),
            payout_type="commission",
            payout_status="pending",
            payment_method=payload.payment_method,
            transaction_id=None,
            remarks=rmk,
            level_depth=level_depth,
            admin_id=admin_id,
        )
        created_ids.append(pid)
        recalculate_partner_portfolio(uid)

    return GeneratePayoutsResponse(payoutsCreated=len(created_ids), payoutIds=created_ids)
