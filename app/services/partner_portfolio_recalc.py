"""
Recompute partner MLM / portfolio summary columns from downline investments and partner commission schedules.
"""

import calendar
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.utils.db_column_names import camel_partner_pk_column
from app.utils.partner_team import count_downline_partners
from app.utils.portfolio_calendar import next_month_bounds_utc

logger = logging.getLogger(__name__)

_INVEST = "investments"

# Principal counted toward participantInvestedTotal / introducer % base
_PRINCIPAL_STATUSES = frozenset(
    ("Active", "Matured", "Completed", "Pending Approval"),
)

# Deals counted for totalDeals (activated / closed pipeline only)
_DEAL_COUNT_STATUSES = frozenset(("Active", "Matured", "Completed"))


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


def recalculate_partner_upline_chain(partner_id: str) -> None:
    """
    Recalculate portfolio for ``partner_id`` and every ancestor reachable via ``introducer``.
    Use after team topology changes (e.g. new partner signup) so ``totalTeamMembers`` stays correct up the tree.
    """
    pid = str(partner_id or "").strip()
    if not pid:
        return
    pk_col = camel_partner_pk_column()
    seen: set[str] = set()
    while pid and pid not in seen:
        seen.add(pid)
        recalculate_partner_portfolio(pid)
        try:
            pr = (
                supabase.table("partners")
                .select("introducer")
                .eq(pk_col, pid)
                .limit(1)
                .execute()
            )
        except APIError:
            break
        if not pr.data:
            break
        pid = str(pr.data[0].get("introducer") or "").strip()


def recalculate_partner_portfolio(partner_id: str) -> None:
    """
    Recompute and persist portfolio / MLM aggregates for one partner (userId = agentId on investments).

    ``portfolioAmount`` / ``paidAmount`` / ``selfEarningAmount`` / ``teamEarningAmount`` count only
    **paid** ``partner_commission_schedules`` rows. ``pendingAmount`` sums **pending** + **due** rows.
    Participant payment schedule PATCH mirrors commission line status per month (see
    ``sync_partner_commission_status_for_month``).
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
    for r in invs:
        iid = str(r.get("investmentId") or "").strip()
        if not iid:
            continue
        st = str(r.get("status") or "").strip()
        if st in _PRINCIPAL_STATUSES:
            participant_invested += _f(r.get("investedAmount"))

    total_deals = sum(
        1
        for r in invs
        if str(r.get("status") or "").strip() in _DEAL_COUNT_STATUSES
    )

    total_team_members = count_downline_partners(pid)

    self_earn_paid = 0.0
    team_earn_paid = 0.0
    commission_pending = 0.0
    per_month_pending = 0.0
    nm_lo, nm_hi = next_month_bounds_utc()
    upcoming_next_month = 0.0
    lo_iso, hi_iso = nm_lo.isoformat(), nm_hi.isoformat()
    try:
        ce_res = (
            supabase.table("partner_commission_schedules")
            .select("amount,status,level,payoutDate")
            .eq("beneficiaryPartnerId", pid)
            .execute()
        )
        for row in ce_res.data or []:
            st = str(row.get("status") or "").strip()
            if st not in ("pending", "due", "paid"):
                continue
            a = _f(row.get("amount"))
            lv = int(row.get("level") or 0)
            if st == "paid":
                if lv <= 0:
                    self_earn_paid += a
                else:
                    team_earn_paid += a
            elif st in ("pending", "due"):
                commission_pending += a
                pds = str(row.get("payoutDate") or "")
                if pds and month_lo <= pds <= month_hi:
                    per_month_pending += a
                if pds and lo_iso <= pds <= hi_iso:
                    upcoming_next_month += a
    except APIError as e:
        logger.warning(
            "recalculate_partner_portfolio: commission schedules query failed for %s: %s",
            pid,
            e,
        )

    portfolio_amount = self_earn_paid + team_earn_paid
    paid_total = portfolio_amount

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
        "pendingAmount": round(commission_pending, 2),
        "perMonthPendingAmount": round(per_month_pending, 2),
        "participantInvestedTotal": round(participant_invested, 2),
        "introducerCommissionAmount": introducer_amt,
        "selfEarningAmount": round(self_earn_paid, 2),
        "teamEarningAmount": round(team_earn_paid, 2),
        "totalDeals": int(total_deals),
        "totalTeamMembers": int(total_team_members),
        "upcomingNetNextMonthPayment": round(upcoming_next_month, 2),
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
