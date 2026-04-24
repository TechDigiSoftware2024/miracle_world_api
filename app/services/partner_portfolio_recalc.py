"""
Recompute partner MLM / book summary columns from downline investments, schedules, and payouts.
"""

import calendar
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.utils.db_column_names import camel_partner_pk_column

logger = logging.getLogger(__name__)

_INVEST = "investments"
_PS = "payment_schedules"
_PAYOUTS = "payouts"

# Principal counted toward participantInvestedTotal / introducer % base
_PRINCIPAL_STATUSES = frozenset(
    ("Active", "Matured", "Completed", "Pending Approval"),
)


def _f(x: Any) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _month_bounds_utc(now: Optional[datetime] = None) -> tuple[str, str]:
    n = now or datetime.now(timezone.utc)
    y, m = n.year, n.month
    start = datetime(y, m, 1, 0, 0, 0, tzinfo=timezone.utc)
    last_d = calendar.monthrange(y, m)[1]
    end = datetime(y, m, last_d, 23, 59, 59, tzinfo=timezone.utc)
    return (start.isoformat(), end.isoformat())


def recalculate_partner_portfolio(partner_id: str) -> None:
    """
    Recompute and persist portfolio / MLM aggregates for one partner (userId = agentId on investments).
    """
    pid = str(partner_id or "").strip()
    if not pid:
        return
    pk_col = camel_partner_pk_column()
    now = datetime.now(timezone.utc).isoformat()
    month_lo, month_hi = _month_bounds_utc()

    try:
        inv_res = (
            supabase.table(_INVEST)
            .select("*")
            .eq("agentId", pid)
            .execute()
        )
        invs = list(inv_res.data or [])
    except APIError as e:
        logger.warning("recalculate_partner_portfolio: investments query failed for %s: %s", pid, e)
        return

    participant_invested = 0.0
    inv_ids_principal: list[str] = []
    inv_by_id: dict[str, dict] = {}
    for r in invs:
        iid = str(r.get("investmentId") or "").strip()
        if not iid:
            continue
        inv_by_id[iid] = r
        st = str(r.get("status") or "").strip()
        if st in _PRINCIPAL_STATUSES:
            participant_invested += _f(r.get("investedAmount"))
            inv_ids_principal.append(iid)

    schedule_pending_total = 0.0
    per_month_pending = 0.0
    if inv_ids_principal:
        try:
            ps_res = supabase.table(_PS).select("*").in_("investmentId", inv_ids_principal).execute()
        except APIError as e:
            logger.warning("recalculate_partner_portfolio: schedules query failed for %s: %s", pid, e)
            ps_res = type("R", (), {"data": []})()

        for line in ps_res.data or []:
            iid = str(line.get("investmentId") or "").strip()
            if iid not in inv_by_id:
                continue
            amt = _f(line.get("amount"))
            st = str(line.get("status") or "").strip()
            if st in ("pending", "due"):
                schedule_pending_total += amt
                pdate = str(line.get("payoutDate") or "")
                if pdate and month_lo <= pdate <= month_hi:
                    per_month_pending += amt

    portfolio_amount = participant_invested + schedule_pending_total

    paid_total = 0.0
    pending_total = 0.0
    self_earn = 0.0
    team_earn = 0.0
    try:
        po_res = (
            supabase.table(_PAYOUTS)
            .select("amount,status,levelDepth")
            .eq("userId", pid)
            .eq("recipientType", "partner")
            .execute()
        )
        for p in po_res.data or []:
            a = _f(p.get("amount"))
            st = str(p.get("status") or "").strip()
            if st == "paid":
                paid_total += a
                depth = p.get("levelDepth")
                if depth is None or int(depth or 0) <= 1:
                    self_earn += a
                elif int(depth) >= 2:
                    team_earn += a
            elif st in ("pending", "processing"):
                pending_total += a
    except APIError as e:
        logger.warning("recalculate_partner_portfolio: payouts query failed for %s: %s", pid, e)

    rate_pct = 0.0
    try:
        pr = supabase.table("partners").select("*").eq(pk_col, pid).limit(1).execute()
        if pr.data:
            row = pr.data[0]
            rate_pct = _f(row.get("introducerCommission"))
            if rate_pct == 0 and row.get("commission") is not None:
                rate_pct = _f(row.get("commission"))
    except APIError:
        pass

    introducer_amt = round(participant_invested * (rate_pct / 100.0), 2)

    patch: dict = {
        "portfolioAmount": round(portfolio_amount, 2),
        "paidAmount": round(paid_total, 2),
        "pendingAmount": round(pending_total, 2),
        "perMonthPendingAmount": round(per_month_pending, 2),
        "participantInvestedTotal": round(participant_invested, 2),
        "introducerCommissionAmount": introducer_amt,
        "selfEarningAmount": round(self_earn, 2),
        "teamEarningAmount": round(team_earn, 2),
        "portfolioUpdatedAt": now,
    }

    try:
        supabase.table("partners").update(patch).eq(pk_col, pid).execute()
    except APIError as e:
        raw = e.args[0] if e.args else {}
        missing = "42703" in str(raw) or "column" in str(e).lower() if e else True
        if missing:
            logger.warning(
                "recalculate_partner_portfolio: update failed (run supabase_partners_mlm_portfolio_columns.sql?) %s: %s",
                pid,
                e,
            )
        else:
            logger.warning("recalculate_partner_portfolio: update failed for %s: %s", pid, e)
