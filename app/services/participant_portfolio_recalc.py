"""
Recalculate participant portfolio summary columns (investments + schedules + payouts).

For investments with isProfitCapitalPerMonth, each schedule line and linked payout
counts only the profit share of the amount (monthly = M, capital = P/duration,
profit share = (M - capital)/M of each cash amount) so principal is not double-counted
in totalPortfolioValue. Non P+C schedule lines and payouts count in full (returns).

Paid ``payouts`` rows that mirror already-counted **payment_schedules** (remarks contain
``participantScheduleIds=`` from mark-paid + recordPayouts) do not add to portfolio again;
the accrual is in the paid schedule lines. Standalone payouts (e.g. manual or maturity)
still count.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.services.partner_portfolio_recalc import recalculate_partner_portfolio
from app.utils.db_column_names import (
    camel_participant_pk_column,
    camel_partner_pk_column,
)
from app.utils.portfolio_calendar import next_month_bounds_utc, parse_timestamptz

logger = logging.getLogger(__name__)

_INVEST = "investments"
_PS = "payment_schedules"
_PAYOUTS = "payouts"
_ACTIVE_STATUSES = frozenset(
    ("Processing", "Pending Approval", "Active", "Matured")
)
_IN_CHUNK = 80


def _chunked(ids: list[str], size: int) -> list[list[str]]:
    return [ids[i : i + size] for i in range(0, len(ids), size)]


def _f(x: Any) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _line_profit_for_portfolio(inv: dict, line_amount: float) -> float:
    """
    Portion of a paid schedule line that counts as profit/return (not return of
    principal) for portfolio when isProfitCapitalPerMonth; otherwise the full line.
    """
    a = _f(line_amount)
    if a <= 0:
        return 0.0
    if not bool(inv.get("isProfitCapitalPerMonth")):
        return a
    p = _f(inv.get("investedAmount"))
    m = _f(inv.get("monthlyPayout"))
    d = int(inv.get("durationMonths") or 0)
    if m <= 0 or d <= 0:
        return a
    cap = p / d
    profit_per = max(0.0, m - cap)
    return a * (profit_per / m)


def _payout_is_schedule_mirror(remarks: object) -> bool:
    """True when this payout row duplicates payment_schedules already rolled into portfolio."""
    s = str(remarks or "").lower()
    return "participantscheduleids=" in s


def _payout_profit_for_portfolio(inv: Optional[dict], amount: float) -> float:
    a = _f(amount)
    if a <= 0:
        return 0.0
    if inv is None:
        return a
    if not bool(inv.get("isProfitCapitalPerMonth")):
        return a
    p = _f(inv.get("investedAmount"))
    m = _f(inv.get("monthlyPayout"))
    d = int(inv.get("durationMonths") or 0)
    if m <= 0 or d <= 0:
        return a
    cap = p / d
    profit_per = max(0.0, m - cap)
    return a * (profit_per / m)


def recalculate_participant_portfolio(participant_id: str) -> None:
    """
    Recompute and persist portfolio fields for one participant. Best-effort: logs
    and returns on error so callers are not broken.
    """
    pid = str(participant_id or "").strip()
    if not pid:
        return
    p_col = camel_participant_pk_column()
    now = datetime.now(timezone.utc).isoformat()

    try:
        inv_res = (
            supabase.table(_INVEST)
            .select("*")
            .eq("participantId", pid)
            .execute()
        )
        invs = list(inv_res.data or [])
    except APIError as e:
        logger.warning("recalculate_participant_portfolio: investments query failed for %s: %s", pid, e)
        return

    inv_by_id: dict[str, dict] = {}
    total_principal = 0.0
    active_count = 0
    for r in invs:
        iid = str(r.get("investmentId") or "").strip()
        if iid:
            inv_by_id[iid] = r
        total_principal += _f(r.get("investedAmount"))
        st = str(r.get("status") or "").strip()
        if st in _ACTIVE_STATUSES:
            active_count += 1

    inv_ids = list(inv_by_id.keys())
    schedule_pending = 0.0
    schedule_paid = 0.0
    schedule_profit = 0.0
    nm_lo, nm_hi = next_month_bounds_utc()
    upcoming_next_month = 0.0

    if inv_ids:
        try:
            ps_res = supabase.table(_PS).select("*").in_("investmentId", inv_ids).execute()
        except APIError as e:
            logger.warning("recalculate_participant_portfolio: schedules query failed for %s: %s", pid, e)
            ps_res = type("R", (), {"data": []})()

        for line in ps_res.data or []:
            iid = str(line.get("investmentId") or "").strip()
            inv = inv_by_id.get(iid) or {}
            amt = _f(line.get("amount"))
            st = str(line.get("status") or "").strip()
            if st in ("pending", "due"):
                schedule_pending += amt
                pd = parse_timestamptz(line.get("payoutDate"))
                if pd is not None and nm_lo <= pd <= nm_hi:
                    upcoming_next_month += amt
            elif st == "paid":
                schedule_paid += amt
                schedule_profit += _line_profit_for_portfolio(inv, amt)

    payouts_paid_gross = 0.0
    payouts_profit = 0.0
    try:
        po_res = (
            supabase.table(_PAYOUTS)
            .select("amount,status,investmentId,remarks")
            .eq("userId", pid)
            .eq("recipientType", "participant")
            .execute()
        )
        for p in po_res.data or []:
            if str(p.get("status") or "").strip() != "paid":
                continue
            a = _f(p.get("amount"))
            payouts_paid_gross += a
            if _payout_is_schedule_mirror(p.get("remarks")):
                continue
            iid = str(p.get("investmentId") or "").strip()
            if iid and iid in inv_by_id:
                payouts_profit += _payout_profit_for_portfolio(inv_by_id.get(iid), a)
            else:
                payouts_profit += a
    except APIError as e:
        logger.warning("recalculate_participant_portfolio: payouts query failed for %s: %s", pid, e)

    total_portfolio = total_principal + schedule_profit + payouts_profit

    patch: dict = {
        "activeInvestmentsCount": int(active_count),
        "totalPrincipalAmount": round(total_principal, 2),
        "totalInvestment": round(total_principal, 2),
        "pendingScheduleAmount": round(schedule_pending, 2),
        "schedulePaidAmount": round(schedule_paid, 2),
        "payoutsPaidAmount": round(payouts_paid_gross, 2),
        "totalPortfolioValue": round(total_portfolio, 2),
        "upcomingNetNextMonthPayment": round(upcoming_next_month, 2),
        "portfolioUpdatedAt": now,
    }

    try:
        supabase.table("participants").update(patch).eq(p_col, pid).execute()
    except APIError as e:
        raw = e.args[0] if e.args else {}
        missing = "42703" in str(raw) or "column" in str(e).lower() if e else True
        if missing:
            logger.warning(
                "recalculate_participant_portfolio: update failed (add supabase_participants_portfolio_columns.sql?) %s: %s",
                pid,
                e,
            )
        else:
            logger.warning("recalculate_participant_portfolio: update failed for %s: %s", pid, e)


def recalculate_all_participant_portfolios() -> int:
    """
    Run :func:`recalculate_participant_portfolio` for every participant (paginated).
    """
    p_col = camel_participant_pk_column()
    n = 0
    off = 0
    _page = 1000
    while True:
        try:
            res = (
                supabase.table("participants")
                .select(p_col)
                .order(p_col)
                .range(off, off + _page - 1)
                .execute()
            )
        except APIError as e:
            logger.warning("recalculate_all_participant_portfolios: list page %s: %s", off, e)
            break
        rows = list(res.data or [])
        if not rows:
            break
        for r in rows:
            pid = str(r.get(p_col) or "").strip()
            if pid:
                recalculate_participant_portfolio(pid)
                n += 1
        if len(rows) < _page:
            break
        off += _page
    return n


def recalc_from_investment_ids(investment_ids: list[str]) -> None:
    """
    Refresh participant + partner portfolio aggregates affected by these investments.

    Batches DB reads and recalculates each participant / partner at most once, even when
    multiple ``investment_ids`` share the same owner or upline.
    """
    ids = list(
        dict.fromkeys(
            str(x).strip() for x in investment_ids if x is not None and str(x).strip()
        )
    )
    if not ids:
        return

    rows_by: dict[str, dict] = {}
    for batch in _chunked(ids, _IN_CHUNK):
        try:
            r = (
                supabase.table(_INVEST)
                .select("investmentId,participantId,agentId")
                .in_("investmentId", batch)
                .execute()
            )
        except APIError as e:
            logger.warning("recalc_from_investment_ids: investment batch: %s", e)
            continue
        for row in r.data or []:
            iid = str(row.get("investmentId") or "").strip()
            if iid:
                rows_by[iid] = row

    participants: set[str] = set()
    agents: set[str] = set()
    for iid in ids:
        row = rows_by.get(iid)
        if not row:
            continue
        pid = str(row.get("participantId") or "").strip()
        if pid:
            participants.add(pid)
        aid = str(row.get("agentId") or "").strip()
        if aid:
            agents.add(aid)

    pk_col = camel_partner_pk_column()
    all_partner_ids: set[str] = set()
    for aid in agents:
        walk = aid
        seen_chain: set[str] = set()
        while walk and walk not in seen_chain:
            seen_chain.add(walk)
            all_partner_ids.add(walk)
            try:
                pr = (
                    supabase.table("partners")
                    .select("introducer")
                    .eq(pk_col, walk)
                    .limit(1)
                    .execute()
                )
            except APIError:
                break
            if not pr.data:
                break
            walk = str(pr.data[0].get("introducer") or "").strip()

    try:
        for batch in _chunked(ids, _IN_CHUNK):
            bc = (
                supabase.table("partner_commission_schedules")
                .select("beneficiaryPartnerId")
                .in_("investmentId", batch)
                .execute()
            )
            for brow in bc.data or []:
                bid = str(brow.get("beneficiaryPartnerId") or "").strip()
                if bid:
                    all_partner_ids.add(bid)
    except APIError:
        pass

    for pid in participants:
        recalculate_participant_portfolio(pid)
    for bid in all_partner_ids:
        recalculate_partner_portfolio(bid)


def recalc_from_investment_id(investment_id: str) -> None:
    recalc_from_investment_ids([investment_id])
