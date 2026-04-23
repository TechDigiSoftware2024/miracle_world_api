"""
Recalculate participant portfolio summary columns (investments + schedules + payouts).

For investments with isProfitCapitalPerMonth, each schedule line and linked payout
counts only the profit share of the amount (monthly = M, capital = P/duration,
profit share = (M - capital)/M of each cash amount) so principal is not double-counted
in totalPortfolioValue. Non P+C schedule lines and payouts count in full (returns).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.utils.db_column_names import camel_participant_pk_column

logger = logging.getLogger(__name__)

_INVEST = "investments"
_PS = "payment_schedules"
_PAYOUTS = "payouts"
_ACTIVE_STATUSES = frozenset(
    ("Processing", "Pending Approval", "Active", "Matured")
)


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
            elif st == "paid":
                schedule_paid += amt
                schedule_profit += _line_profit_for_portfolio(inv, amt)

    payouts_paid_gross = 0.0
    payouts_profit = 0.0
    try:
        po_res = (
            supabase.table(_PAYOUTS)
            .select("amount,status,investmentId")
            .eq("userId", pid)
            .eq("recipientType", "participant")
            .execute()
        )
        for p in po_res.data or []:
            if str(p.get("status") or "").strip() != "paid":
                continue
            a = _f(p.get("amount"))
            payouts_paid_gross += a
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


def recalc_from_investment_id(investment_id: str) -> None:
    try:
        r = supabase.table(_INVEST).select("participantId").eq("investmentId", investment_id).limit(1).execute()
    except APIError as e:
        logger.warning("recalc_from_investment_id: %s", e)
        return
    if not r.data:
        return
    pid = str(r.data[0].get("participantId") or "").strip()
    if pid:
        recalculate_participant_portfolio(pid)
