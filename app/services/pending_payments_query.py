"""Build admin pending-payment rollups (participant schedules + partner commission lines)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.schemas.pending_payments_admin import (
    PartnerCommissionPendingLineDetail,
    PartnerGroupPendingRow,
    ParticipantPendingRow,
    PendingPaymentsListResponse,
    PendingPaymentsSummary,
)
from app.utils.db_column_names import camel_participant_pk_column, camel_partner_pk_column

_BATCH = 120
_PAGE = 1000


def _chunks(xs: list, n: int):
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def _select_all_paged(table: str, *, select_cols: str = "*") -> list[dict]:
    out: list[dict] = []
    start = 0
    while True:
        end = start + _PAGE - 1
        res = supabase.table(table).select(select_cols).range(start, end).execute()
        rows = list(res.data or [])
        out.extend(rows)
        if len(rows) < _PAGE:
            break
        start += _PAGE
    return out


def _select_in_all_paged(
    table: str,
    in_col: str,
    in_values: list[str],
    *,
    select_cols: str = "*",
) -> list[dict]:
    if not in_values:
        return []
    out: list[dict] = []
    start = 0
    while True:
        end = start + _PAGE - 1
        res = (
            supabase.table(table)
            .select(select_cols)
            .in_(in_col, in_values)
            .range(start, end)
            .execute()
        )
        rows = list(res.data or [])
        out.extend(rows)
        if len(rows) < _PAGE:
            break
        start += _PAGE
    return out


def _date_key(iso_val: Any) -> str:
    s = str(iso_val or "")
    if len(s) >= 10:
        return s[:10]
    return ""


def _passes_date_filter(
    payout_raw: Any,
    exact_date: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
) -> bool:
    ex = (exact_date or "").strip()[:10]
    df = (date_from or "").strip()[:10]
    dt = (date_to or "").strip()[:10]
    if not (ex or df or dt):
        return True
    key = _date_key(payout_raw)
    if not key:
        return False
    if ex:
        return key == ex
    if df and key < df:
        return False
    if dt and key > dt:
        return False
    return True


def _coerce_dt(val: Any) -> datetime:
    if isinstance(val, datetime):
        d = val
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    s = str(val).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(timezone.utc)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def query_pending_payments_rollup(
    *,
    recipient_type: str = "all",
    investment_status: str = "Active",
    exact_date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    month_number: Optional[int] = None,
    user_id_query: Optional[str] = None,
    name_query: Optional[str] = None,
    group_partner_by: str = "auto",
) -> PendingPaymentsListResponse:
    """
    ``group_partner_by``: ``auto`` collapses partner rows by beneficiary only when a date filter is set;
    ``beneficiary`` always collapses by beneficiary; ``month`` always groups beneficiary+monthNumber.
    """
    rq = (recipient_type or "all").strip().lower()
    iq = (user_id_query or "").strip().lower()
    nq = (name_query or "").strip().lower()
    ex = (exact_date or "").strip() or None
    df = (date_from or "").strip() or None
    dt = (date_to or "").strip() or None
    has_date = bool(ex or df or dt)

    gmode = (group_partner_by or "auto").strip().lower()
    if gmode not in ("auto", "beneficiary", "month"):
        gmode = "auto"
    if gmode == "auto":
        collapse_partner = has_date
    elif gmode == "beneficiary":
        collapse_partner = True
    else:
        collapse_partner = False

    try:
        inv_rows = _select_all_paged(
            "investments",
            select_cols="investmentId,participantId,agentId,fundId,fundName,status",
        )
        if investment_status and str(investment_status).strip().lower() != "all":
            st = str(investment_status).strip().lower()
            inv_rows = [
                r for r in inv_rows if str(r.get("status") or "").strip().lower() == st
            ]
    except APIError:
        inv_rows = []

    inv_map: dict[str, dict] = {}
    for r in inv_rows:
        iid = str(r.get("investmentId") or "").strip()
        if iid:
            inv_map[iid] = r

    inv_ids = list(inv_map.keys())
    p_pk = camel_participant_pk_column()
    a_pk = camel_partner_pk_column()

    pids_all = {str(v.get("participantId") or "").strip() for v in inv_map.values()}
    pids_all.discard("")
    part_by_id: dict[str, dict] = {}
    for chunk in _chunks(list(pids_all), _BATCH):
        try:
            pr = (
                supabase.table("participants")
                .select(f"{p_pk},name,phone")
                .in_(p_pk, chunk)
                .execute()
            )
            for row in pr.data or []:
                part_by_id[str(row.get(p_pk) or "")] = row
        except APIError:
            continue

    participant_rows: list[ParticipantPendingRow] = []
    if rq in ("all", "participant") and inv_ids:
        sched_rows: list[dict] = []
        for chunk in _chunks(inv_ids, _BATCH):
            try:
                srows = _select_in_all_paged(
                    "payment_schedules", "investmentId", chunk, select_cols="*"
                )
                sched_rows.extend(
                    [
                        r
                        for r in srows
                        if str(r.get("status") or "").strip().lower() in ("pending", "due")
                    ]
                )
            except APIError:
                continue

        for s in sched_rows:
            iid = str(s.get("investmentId") or "").strip()
            if iid not in inv_map:
                continue
            inv = inv_map[iid]
            pid = str(inv.get("participantId") or "").strip()
            part = part_by_id.get(pid) or {}
            pname = str(part.get("name") or "")
            pphone = str(part.get("phone") or "")
            if iq and iq not in pid.lower():
                continue
            if nq and nq not in pname.lower():
                continue
            mn = int(s.get("monthNumber") or 0)
            if month_number is not None and mn != month_number:
                continue
            if not _passes_date_filter(s.get("payoutDate"), ex, df, dt):
                continue
            participant_rows.append(
                ParticipantPendingRow(
                    rowType="participant",
                    scheduleId=int(s["id"]),
                    investmentId=iid,
                    participantId=pid,
                    participantName=pname,
                    participantPhone=pphone,
                    monthNumber=mn,
                    amount=float(s.get("amount") or 0),
                    payoutDate=_coerce_dt(s.get("payoutDate")),
                    status=str(s.get("status") or "pending"),
                    paymentMethod="BANK",
                    fundId=str(inv.get("fundId") or ""),
                    fundName=str(inv.get("fundName") or ""),
                )
            )

    partner_groups: list[PartnerGroupPendingRow] = []
    if rq in ("all", "partner") and inv_ids:
        pc_rows: list[dict] = []
        for chunk in _chunks(inv_ids, _BATCH):
            try:
                crows = _select_in_all_paged(
                    "partner_commission_schedules", "investmentId", chunk, select_cols="*"
                )
                pc_rows.extend(
                    [
                        r
                        for r in crows
                        if str(r.get("status") or "").strip().lower() in ("pending", "due")
                    ]
                )
            except APIError:
                continue

        ben_ids = {str(r.get("beneficiaryPartnerId") or "").strip() for r in pc_rows}
        ben_ids.discard("")
        partner_by_id: dict[str, dict] = {}
        for chunk in _chunks(list(ben_ids), _BATCH):
            try:
                ar = (
                    supabase.table("partners")
                    .select(f"{a_pk},name,phone")
                    .in_(a_pk, chunk)
                    .execute()
                )
                for row in ar.data or []:
                    partner_by_id[str(row.get(a_pk) or "")] = row
            except APIError:
                continue

        filtered_lines: list[PartnerCommissionPendingLineDetail] = []
        for r in pc_rows:
            iid = str(r.get("investmentId") or "").strip()
            if iid not in inv_map:
                continue
            inv = inv_map[iid]
            pid = str(inv.get("participantId") or "").strip()
            part = part_by_id.get(pid) or {}
            pname = str(part.get("name") or "")
            bid = str(r.get("beneficiaryPartnerId") or "").strip()
            bp = partner_by_id.get(bid) or {}
            bname = str(bp.get("name") or "")
            if iq and iq not in bid.lower() and iq not in pid.lower():
                continue
            if nq and nq not in bname.lower() and nq not in pname.lower():
                continue
            mn = int(r.get("monthNumber") or 0)
            if month_number is not None and mn != month_number:
                continue
            if not _passes_date_filter(r.get("payoutDate"), ex, df, dt):
                continue
            filtered_lines.append(
                PartnerCommissionPendingLineDetail(
                    commissionScheduleId=int(r["id"]),
                    beneficiaryPartnerId=bid,
                    investmentId=iid,
                    participantId=pid,
                    participantName=pname,
                    monthNumber=mn,
                    amount=float(r.get("amount") or 0),
                    payoutDate=_coerce_dt(r.get("payoutDate")),
                    status=str(r.get("status") or "pending"),
                    level=int(r.get("level") or 0),
                    sourcePartnerId=str(r.get("sourcePartnerId") or ""),
                )
            )

        grouped: dict[str, list[PartnerCommissionPendingLineDetail]] = defaultdict(list)
        for ln in filtered_lines:
            if collapse_partner:
                key = ln.beneficiary_partner_id
            else:
                key = f"{ln.beneficiary_partner_id}__{ln.month_number}"
            grouped[key].append(ln)

        for gkey, lines in grouped.items():
            lines.sort(key=lambda x: (x.payout_date, x.commission_schedule_id))
            bid = lines[0].beneficiary_partner_id
            bp = partner_by_id.get(bid) or {}
            bname = str(bp.get("name") or "")
            bphone = str(bp.get("phone") or "")
            months = sorted({ln.month_number for ln in lines})
            if len(months) == 1:
                ml = f"Mo.{months[0]}"
            else:
                ml = f"Mo.{months[0]}–{months[-1]}"
            st_all = [ln.status.lower() for ln in lines]
            disp = "due" if any(s == "due" for s in st_all) else "pending"
            inv_count = len({ln.investment_id for ln in lines})
            partner_groups.append(
                PartnerGroupPendingRow(
                    rowType="partner",
                    groupKey=gkey,
                    beneficiaryPartnerId=bid,
                    beneficiaryName=bname,
                    beneficiaryPhone=bphone,
                    totalAmount=round(sum(ln.amount for ln in lines), 2),
                    lineCount=len(lines),
                    investmentCount=inv_count,
                    monthCount=len(months),
                    monthLabel=ml,
                    earliestPayoutDate=min(ln.payout_date for ln in lines),
                    displayStatus=disp,
                    lines=lines,
                )
            )

    all_rows: list = list(participant_rows) + list(partner_groups)
    all_rows.sort(
        key=lambda r: r.payout_date
        if isinstance(r, ParticipantPendingRow)
        else r.earliest_payout_date
    )

    tap = round(sum(r.amount for r in participant_rows), 2)
    tpar = round(sum(g.total_amount for g in partner_groups), 2)
    summary = PendingPaymentsSummary(
        participantRowCount=len(participant_rows),
        partnerGroupCount=len(partner_groups),
        totalRowCount=len(participant_rows) + len(partner_groups),
        totalAmountParticipants=tap,
        totalAmountPartners=tpar,
        grandTotal=round(tap + tpar, 2),
    )
    return PendingPaymentsListResponse(summary=summary, rows=all_rows)
