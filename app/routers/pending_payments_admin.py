from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.pending_payments_admin import (
    MarkPaidItemResult,
    MarkPaidRequest,
    MarkPaidResponse,
    PendingPaymentsListResponse,
)
from app.services.mark_paid_post_process import run_participant_mark_paid_post_process
from app.services.payout_recording import (
    build_participant_payout_groups,
    build_partner_payout_groups,
    load_paid_payout_remarks_by_users,
    record_participant_payouts,
    record_partner_payouts,
)
from app.services.pending_payments_query import query_pending_payments_rollup
from app.services.schedule_payout_workflow import (
    collect_participant_mark_paid_post_process,
    fetch_commission_schedule_rows,
    mark_partner_commission_schedules_paid,
    mark_payment_schedules_paid_batch,
)
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/pending-payments", tags=["Admin", "Pending payments"])

_INV_CHUNK = 80


def _chunks(xs: list, n: int):
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def _fetch_inv_to_participant(investment_ids: list[str]) -> dict[str, str]:
    inv_to_part: dict[str, str] = {}
    ids = sorted({str(x).strip() for x in investment_ids if str(x).strip()})
    for chunk in _chunks(ids, _INV_CHUNK):
        try:
            inv_r = (
                supabase.table("investments")
                .select("investmentId,participantId")
                .in_("investmentId", chunk)
                .execute()
            )
        except APIError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=format_api_error(e),
            ) from e
        for r in inv_r.data or []:
            inv_to_part[str(r.get("investmentId") or "").strip()] = str(
                r.get("participantId") or ""
            ).strip()
    return inv_to_part


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
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_role(["admin"])),
):
    """Mark participant payment_schedules and/or partner_commission_schedules as paid; optional payout audit rows.

    **Payout rows**: By default ``recordPayouts`` is **true**, so paid ``payouts`` audit rows are created
    unless the client sets ``recordPayouts: false`` (legacy / reconciliation-only).

    Paid schedules that were already marked in a prior call but never received a matching payout row
    (per schedule id in ``remarks``) are included when ``recordPayouts`` is true.

    Portfolio / commission sync runs in the background after the response.
    """
    if not payload.participant_schedule_ids and not payload.partner_commission_schedule_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide participantScheduleIds and/or partnerCommissionScheduleIds",
        )
    admin_id = str(current_user.get("userId", "") or "").strip()
    results: List[MarkPaidItemResult] = []
    payouts_recorded = 0
    post_process_inv_months: dict[str, list[int]] = {}

    if payload.participant_schedule_ids:
        ordered_ps = [int(x) for x in payload.participant_schedule_ids if x is not None]
        try:
            ps_batch = mark_payment_schedules_paid_batch(
                ordered_ps, defer_post_save=True
            )
        except ValueError as e:
            for psid_int in ordered_ps:
                results.append(
                    MarkPaidItemResult(
                        ref=str(psid_int),
                        kind="participant",
                        ok=False,
                        detail=str(e),
                    )
                )
        else:
            post_process_inv_months = collect_participant_mark_paid_post_process(ps_batch)
            schedule_triples = [
                (psid_int, row, err) for psid_int, (row, _ch, err) in zip(ordered_ps, ps_batch)
            ]
            for psid_int, (row, _changed, err) in zip(ordered_ps, ps_batch):
                if err:
                    results.append(
                        MarkPaidItemResult(
                            ref=str(psid_int),
                            kind="participant",
                            ok=False,
                            detail=err,
                        )
                    )
                else:
                    results.append(
                        MarkPaidItemResult(
                            ref=str(psid_int), kind="participant", ok=True, detail=None
                        )
                    )

            if payload.record_payouts:
                paid_iids = {
                    str(row.get("investmentId") or "").strip()
                    for _psid, row, err in schedule_triples
                    if not err
                    and str(row.get("status") or "").strip().lower() == "paid"
                }
                paid_iids.discard("")
                inv_to_part = _fetch_inv_to_participant(sorted(paid_iids))
                participant_groups = build_participant_payout_groups(
                    schedule_triples, inv_to_part
                )
                for psid, row, err in schedule_triples:
                    if err:
                        continue
                    iid = str(row.get("investmentId") or "").strip()
                    uid = inv_to_part.get(iid, "").strip()
                    if iid and not uid:
                        results.append(
                            MarkPaidItemResult(
                                ref=str(psid),
                                kind="participant",
                                ok=False,
                                detail=f"investment {iid} has no participantId (payout not recorded)",
                            )
                        )
                if participant_groups:
                    paid_remarks = load_paid_payout_remarks_by_users(
                        list(participant_groups.keys()), "participant"
                    )
                    payouts_recorded += record_participant_payouts(
                        by_participant=participant_groups,
                        paid_remarks_index=paid_remarks,
                        payment_method=payload.payment_method,
                        transaction_id=payload.transaction_id,
                        base_remarks=payload.remarks,
                        admin_id=admin_id,
                    )

    pids = sorted({int(x) for x in payload.partner_commission_schedule_ids if x is not None})
    partner_inv_ids: list[str] = []
    if pids:
        ref = ",".join(str(i) for i in pids)
        try:
            mark_partner_commission_schedules_paid(pids, defer_recalc=True)
            results.append(
                MarkPaidItemResult(ref=ref, kind="partner", ok=True, detail=None)
            )
            if payload.record_payouts:
                commission_rows = fetch_commission_schedule_rows(pids)
                partner_inv_ids = sorted(
                    {
                        str(r.get("investmentId") or "").strip()
                        for r in commission_rows
                        if str(r.get("investmentId") or "").strip()
                    }
                )
                partner_groups = build_partner_payout_groups(commission_rows)
                if partner_groups:
                    partner_paid_remarks = load_paid_payout_remarks_by_users(
                        list(partner_groups.keys()), "partner"
                    )
                    payouts_recorded += record_partner_payouts(
                        by_beneficiary=partner_groups,
                        paid_remarks_index=partner_paid_remarks,
                        payment_method=payload.payment_method,
                        transaction_id=payload.transaction_id,
                        base_remarks=payload.remarks,
                        admin_id=admin_id,
                        batch_key=payload.partner_payout_batch_key,
                    )
        except ValueError as e:
            results.append(
                MarkPaidItemResult(ref=ref, kind="partner", ok=False, detail=str(e))
            )

    if post_process_inv_months:
        background_tasks.add_task(
            run_participant_mark_paid_post_process, post_process_inv_months
        )
    if partner_inv_ids:
        from app.services.participant_portfolio_recalc import recalc_from_investment_ids

        background_tasks.add_task(recalc_from_investment_ids, partner_inv_ids)

    return MarkPaidResponse(results=results, payoutsRecorded=payouts_recorded)
