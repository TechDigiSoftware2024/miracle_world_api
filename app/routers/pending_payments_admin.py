from __future__ import annotations

import re
from collections import defaultdict
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


def _participant_aggregate_tag(schedule_ids: list[int]) -> str:
    return "aggregated participantScheduleIds=" + ",".join(
        str(i) for i in sorted(set(schedule_ids))
    )


def _partner_aggregate_tag(commission_ids: list[int]) -> str:
    return "aggregated commissionScheduleIds=" + ",".join(
        str(i) for i in sorted(set(commission_ids))
    )


def _payout_remarks_contain_tag(
    user_id: str,
    recipient_type: str,
    tag: str,
    *,
    status: Optional[str] = None,
) -> bool:
    """Idempotency: optional status filter (e.g. paid vs pending)."""
    uid = str(user_id or "").strip()
    if not uid or not tag:
        return False
    try:
        q = (
            supabase.table("payouts")
            .select("payoutId")
            .eq("userId", uid)
            .eq("recipientType", recipient_type)
            .ilike("remarks", f"%{tag}%")
        )
        if status:
            q = q.eq("status", status)
        res = q.limit(1).execute()
    except APIError:
        return False
    return bool(res.data)


def _sanitize_batch_key(k: Optional[str]) -> Optional[str]:
    if k is None:
        return None
    s = str(k).strip()
    if re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", s):
        return s
    return None


def _find_consolidated_partner_payout_row(
    uid: str,
    payout_status: str,
    *,
    batch_key: Optional[str],
    transaction_id: Optional[str],
) -> Optional[dict]:
    """Partner row to merge into (same batch key, else same transaction id) for this user and status."""
    uid = str(uid or "").strip()
    if not uid:
        return None
    st = str(payout_status or "").strip()
    try:
        if batch_key:
            r = (
                supabase.table("payouts")
                .select("*")
                .eq("userId", uid)
                .eq("recipientType", "partner")
                .eq("status", st)
                .ilike("remarks", f"%payoutBatchKey={batch_key}%")
                .order("createdAt", desc=True)
                .limit(1)
                .execute()
            )
            if r.data:
                return r.data[0]
        tid = (transaction_id or "").strip()
        if tid:
            r = (
                supabase.table("payouts")
                .select("*")
                .eq("userId", uid)
                .eq("recipientType", "partner")
                .eq("status", st)
                .eq("transactionId", tid)
                .order("createdAt", desc=True)
                .limit(1)
                .execute()
            )
            if r.data:
                return r.data[0]
    except APIError:
        return None
    return None


def _merge_update_partner_payout_row(
    existing: dict,
    *,
    add_amount: float,
    new_payout_date: datetime,
    append_remarks: str,
    payment_method: str,
    transaction_id: Optional[str],
    admin_id: str,
) -> None:
    """Add amount and extend remarks; max payout date; investmentId cleared on merge."""
    pid = str(existing.get("payoutId") or "").strip()
    if not pid:
        return
    old_amt = float(existing.get("amount") or 0)
    new_amt = round(old_amt + float(add_amount), 2)
    old_pd = _dt_for_payout(existing.get("payoutDate"))
    max_pd = new_payout_date if new_payout_date > old_pd else old_pd
    pd = max_pd if max_pd.tzinfo else max_pd.replace(tzinfo=timezone.utc)
    remarks = f"{str(existing.get('remarks') or '').strip()} {append_remarks}".strip()
    now = datetime.now(timezone.utc).isoformat()
    body: dict = {
        "amount": new_amt,
        "payoutDate": pd.isoformat(),
        "remarks": remarks,
        "investmentId": None,
        "paymentMethod": payment_method,
        "levelDepth": None,
        "updatedAt": now,
    }
    tid = (transaction_id or "").strip()
    if tid:
        body["transactionId"] = tid
    if admin_id:
        body["createdByAdminId"] = str(admin_id).strip()
    try:
        supabase.table("payouts").update(body).eq("payoutId", pid).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


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

    Partner ``recordPayouts``: one **paid** ``payouts`` row per **beneficiaryPartnerId** in this request
    (amounts summed). Optional ``partnerPayoutBatchKey`` (same value on multiple API calls) or a shared
    ``transactionId`` merges additional lines into that partner's existing paid row instead of creating another.
    ``remarks`` include ``aggregated commissionScheduleIds=…`` and ``investmentIds=…``.

    Participant ``recordPayouts``: **one paid** row per **participantId** in this request with the same pattern.
    """
    if not payload.participant_schedule_ids and not payload.partner_commission_schedule_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide participantScheduleIds and/or partnerCommissionScheduleIds",
        )
    admin_id = str(current_user.get("userId", "") or "").strip()
    batch_key = _sanitize_batch_key(payload.partner_payout_batch_key)
    txn_for_merge = (payload.transaction_id or "").strip() or None
    results: List[MarkPaidItemResult] = []
    payouts_recorded = 0
    participant_acc: dict[str, list[tuple[int, dict, str]]] = defaultdict(list)

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
                    participant_acc[uid].append((int(psid), row, iid))
        except ValueError as e:
            results.append(
                MarkPaidItemResult(
                    ref=str(psid),
                    kind="participant",
                    ok=False,
                    detail=str(e),
                )
            )

    if payload.record_payouts:
        for uid, items in participant_acc.items():
            sids = [t[0] for t in items]
            tag = _participant_aggregate_tag(sids)
            if _payout_remarks_contain_tag(uid, "participant", tag, status="paid"):
                continue
            total_amt = sum(float(t[1].get("amount") or 0) for t in items)
            max_pd = max(_dt_for_payout(t[1].get("payoutDate")) for t in items)
            iids = sorted({t[2] for t in items if t[2]})
            inv_single: Optional[str] = iids[0] if len(iids) == 1 else None
            rmk = (payload.remarks or "").strip()
            rmk = f"{rmk} {tag} investmentIds={','.join(iids)}".strip()
            _insert_payout_row(
                user_id=uid,
                recipient_type="participant",
                amount=total_amt,
                investment_id=inv_single,
                payout_date=max_pd,
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
                by_beneficiary: dict[str, list[dict]] = defaultdict(list)
                for r in fetched.data or []:
                    if str(r.get("status") or "").strip().lower() != "paid":
                        continue
                    uid = str(r.get("beneficiaryPartnerId") or "").strip()
                    if uid:
                        by_beneficiary[uid].append(r)
                for uid, paid_rows in by_beneficiary.items():
                    cids = [int(r["id"]) for r in paid_rows]
                    tag = _partner_aggregate_tag(cids)
                    if _payout_remarks_contain_tag(uid, "partner", tag, status="paid"):
                        continue
                    total_amt = sum(float(r.get("amount") or 0) for r in paid_rows)
                    max_pd = max(_dt_for_payout(r.get("payoutDate")) for r in paid_rows)
                    levels = {int(r.get("level") or 0) for r in paid_rows}
                    level_depth: Optional[int] = None
                    if len(levels) == 1:
                        ld0 = next(iter(levels))
                        level_depth = ld0 if ld0 >= 1 else None
                    iids = sorted(
                        {
                            str(r.get("investmentId") or "").strip()
                            for r in paid_rows
                            if str(r.get("investmentId") or "").strip()
                        }
                    )
                    inv_single = iids[0] if len(iids) == 1 else None
                    rmk = (payload.remarks or "").strip()
                    rmk = f"{rmk} {tag} investmentIds={','.join(iids)}".strip()
                    if batch_key:
                        rmk = f"{rmk} payoutBatchKey={batch_key}".strip()
                    exist = _find_consolidated_partner_payout_row(
                        uid,
                        "paid",
                        batch_key=batch_key,
                        transaction_id=txn_for_merge,
                    )
                    if exist:
                        _merge_update_partner_payout_row(
                            exist,
                            add_amount=total_amt,
                            new_payout_date=max_pd,
                            append_remarks=rmk,
                            payment_method=payload.payment_method,
                            transaction_id=txn_for_merge,
                            admin_id=admin_id,
                        )
                    else:
                        _insert_payout_row(
                            user_id=uid,
                            recipient_type="partner",
                            amount=total_amt,
                            investment_id=inv_single,
                            payout_date=max_pd,
                            payout_type="commission",
                            payout_status="paid",
                            payment_method=payload.payment_method,
                            transaction_id=payload.transaction_id,
                            remarks=rmk,
                            level_depth=level_depth,
                            admin_id=admin_id,
                        )
                    payouts_recorded += 1
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
    """Insert **pending** `payouts` rows from schedule lines (does not mark schedules paid).

    One **pending** row per partner beneficiary in this request, or merged across calls using the same
    **partnerPayoutBatchKey** (same beneficiary in each call).
    """
    if not payload.participant_schedule_ids and not payload.partner_commission_schedule_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide participantScheduleIds and/or partnerCommissionScheduleIds",
        )
    admin_id = str(current_user.get("userId", "") or "").strip()
    batch_key = _sanitize_batch_key(payload.partner_payout_batch_key)
    created_ids: List[str] = []

    ps_ids = sorted({int(x) for x in payload.participant_schedule_ids if x is not None})
    if ps_ids:
        sr_all = (
            supabase.table("payment_schedules").select("*").in_("id", ps_ids).execute()
        )
        found_ids = {int(r["id"]) for r in (sr_all.data or [])}
        missing = [i for i in ps_ids if i not in found_ids]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"payment schedule(s) not found: {missing}",
            )
        inv_ids = sorted(
            {
                str(r.get("investmentId") or "").strip()
                for r in (sr_all.data or [])
                if str(r.get("investmentId") or "").strip()
            }
        )
        inv_to_part: dict[str, str] = {}
        if inv_ids:
            ir = (
                supabase.table("investments")
                .select("investmentId,participantId")
                .in_("investmentId", inv_ids)
                .execute()
            )
            for r in ir.data or []:
                inv_to_part[str(r.get("investmentId") or "").strip()] = str(
                    r.get("participantId") or ""
                ).strip()
        by_participant: dict[str, list[dict]] = defaultdict(list)
        for row in sr_all.data or []:
            iid = str(row.get("investmentId") or "").strip()
            pid = inv_to_part.get(iid, "").strip()
            if not pid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"investment {iid} has no participantId",
                )
            by_participant[pid].append(row)

        for uid, rows in by_participant.items():
            for row in rows:
                st = str(row.get("status") or "").strip().lower()
                if st not in ("pending", "due"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"schedule {row.get('id')} is not pending/due",
                    )
            schedule_ids = [int(r["id"]) for r in rows]
            tag = _participant_aggregate_tag(schedule_ids)
            if _payout_remarks_contain_tag(uid, "participant", tag, status="pending"):
                continue
            total_amt = sum(float(r.get("amount") or 0) for r in rows)
            max_pd = max(_dt_for_payout(r.get("payoutDate")) for r in rows)
            iids = sorted(
                {
                    str(r.get("investmentId") or "").strip()
                    for r in rows
                    if str(r.get("investmentId") or "").strip()
                }
            )
            inv_single = iids[0] if len(iids) == 1 else None
            rmk = (payload.remarks or "").strip()
            rmk = f"{rmk} {tag} investmentIds={','.join(iids)}".strip()
            pid = _insert_payout_row(
                user_id=uid,
                recipient_type="participant",
                amount=total_amt,
                investment_id=inv_single,
                payout_date=max_pd,
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

    pc_ids = sorted({int(x) for x in payload.partner_commission_schedule_ids if x is not None})
    if pc_ids:
        cr_all = (
            supabase.table("partner_commission_schedules")
            .select("*")
            .in_("id", pc_ids)
            .execute()
        )
        found_c = {int(r["id"]) for r in (cr_all.data or [])}
        missing_c = [i for i in pc_ids if i not in found_c]
        if missing_c:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"partner commission schedule(s) not found: {missing_c}",
            )
        by_beneficiary: dict[str, list[dict]] = defaultdict(list)
        for row in cr_all.data or []:
            uid = str(row.get("beneficiaryPartnerId") or "").strip()
            if uid:
                by_beneficiary[uid].append(row)

        for uid, rows in by_beneficiary.items():
            for row in rows:
                st = str(row.get("status") or "").strip().lower()
                if st not in ("pending", "due"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"commission line {row.get('id')} is not pending/due",
                    )
            cids = [int(r["id"]) for r in rows]
            tag = _partner_aggregate_tag(cids)
            if _payout_remarks_contain_tag(uid, "partner", tag, status="pending"):
                continue
            total_amt = sum(float(r.get("amount") or 0) for r in rows)
            max_pd = max(_dt_for_payout(r.get("payoutDate")) for r in rows)
            levels = {int(r.get("level") or 0) for r in rows}
            level_depth: Optional[int] = None
            if len(levels) == 1:
                ld0 = next(iter(levels))
                level_depth = ld0 if ld0 >= 1 else None
            iids = sorted(
                {
                    str(r.get("investmentId") or "").strip()
                    for r in rows
                    if str(r.get("investmentId") or "").strip()
                }
            )
            inv_single = iids[0] if len(iids) == 1 else None
            rmk = (payload.remarks or "").strip()
            rmk = f"{rmk} {tag} investmentIds={','.join(iids)}".strip()
            if batch_key:
                rmk = f"{rmk} payoutBatchKey={batch_key}".strip()
            exist = _find_consolidated_partner_payout_row(
                uid,
                "pending",
                batch_key=batch_key,
                transaction_id=None,
            )
            if exist:
                _merge_update_partner_payout_row(
                    exist,
                    add_amount=total_amt,
                    new_payout_date=max_pd,
                    append_remarks=rmk,
                    payment_method=payload.payment_method,
                    transaction_id=None,
                    admin_id=admin_id,
                )
                eid = str(exist.get("payoutId") or "").strip()
                if eid:
                    created_ids.append(eid)
            else:
                pid = _insert_payout_row(
                    user_id=uid,
                    recipient_type="partner",
                    amount=total_amt,
                    investment_id=inv_single,
                    payout_date=max_pd,
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
