"""
Recompute partner MLM / portfolio summary columns from downline investments and partner commission schedules.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.utils.db_column_names import camel_partner_pk_column
from app.utils.partner_team import count_downline_partners, downline_partner_ids_including_self
from app.utils.portfolio_calendar import next_month_bounds_utc, parse_timestamptz

logger = logging.getLogger(__name__)

_INVEST = "investments"

# Principal counted toward participantInvestedTotal / introducer % base
_PRINCIPAL_STATUSES = frozenset(
    ("Active", "Matured", "Completed", "Pending Approval"),
)

# Deals counted for totalDeals (activated / closed pipeline only)
_DEAL_COUNT_STATUSES = frozenset(("Active", "Matured", "Completed"))

# PostgREST often caps responses (~1000 rows); paginate so totals are complete.
_PAGE = 1000


def _f(x: Any) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _fetch_all_commission_lines_for_beneficiary(partner_id: str) -> list[dict]:
    """All ``partner_commission_schedules`` rows for this beneficiary (paginated)."""
    pid = str(partner_id or "").strip()
    out: list[dict] = []
    off = 0
    while True:
        try:
            res = (
                supabase.table("partner_commission_schedules")
                .select("amount,status,level,payoutDate")
                .eq("beneficiaryPartnerId", pid)
                .order("id")
                .range(off, off + _PAGE - 1)
                .execute()
            )
        except APIError as e:
            logger.warning("commission schedules page %s for %s: %s", off, pid, e)
            break
        chunk = list(res.data or [])
        if not chunk:
            break
        out.extend(chunk)
        if len(chunk) < _PAGE:
            break
        off += _PAGE
    return out


def _fetch_all_investments_as_agent(partner_id: str) -> list[dict]:
    """All investments where this partner is ``agentId`` (paginated)."""
    pid = str(partner_id or "").strip()
    out: list[dict] = []
    off = 0
    while True:
        try:
            res = (
                supabase.table(_INVEST)
                .select("*")
                .eq("agentId", pid)
                .order("investmentId")
                .range(off, off + _PAGE - 1)
                .execute()
            )
        except APIError as e:
            logger.warning("investments page %s for agent %s: %s", off, pid, e)
            break
        chunk = list(res.data or [])
        if not chunk:
            break
        out.extend(chunk)
        if len(chunk) < _PAGE:
            break
        off += _PAGE
    return out


def _sum_principal_for_agent_ids(agent_ids: list[str]) -> float:
    """Sum ``investedAmount`` for investments whose agent is in ``agent_ids`` and status qualifies."""
    ids = [str(x).strip() for x in agent_ids if str(x).strip()]
    if not ids:
        return 0.0
    total = 0.0
    chunk_size = 80
    st_list = list(_PRINCIPAL_STATUSES)
    for i in range(0, len(ids), chunk_size):
        batch = ids[i : i + chunk_size]
        off = 0
        while True:
            try:
                res = (
                    supabase.table(_INVEST)
                    .select("investedAmount")
                    .in_("agentId", batch)
                    .in_("status", st_list)
                    .order("investmentId")
                    .range(off, off + _PAGE - 1)
                    .execute()
                )
            except APIError as e:
                logger.warning("totalBusiness batch page %s: %s", off, e)
                break
            chunk = list(res.data or [])
            if not chunk:
                break
            for r in chunk:
                total += _f(r.get("investedAmount"))
            if len(chunk) < _PAGE:
                break
            off += _PAGE
    return total


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
    Recompute and persist partner dashboard columns from ``investments`` (as agent) and
    ``partner_commission_schedules`` (as beneficiary). Uses paginated reads so totals are not
    truncated at the PostgREST default row cap.

    - **portfolioAmount** / **paidAmount**: total **paid** commission (self + team) for this partner.
    - **selfEarningAmount**: **paid** rows with **level 0** (direct agent on the deal).
    - **teamEarningAmount**: **paid** rows with **level ≥ 1** (team / upline paid to this partner).
    - **pendingAmount**: sum of **pending** + **due** accruals not yet paid.
    - **upcomingNetNextMonthPayment**: **pending** + **due** with ``payoutDate`` in the **next** UTC month.
    - **totalBusiness**: sum of **investedAmount** (qualifying statuses) for investments where **agentId** is
      this partner or any partner in their downline introducer tree (group book).
    """
    pid = str(partner_id or "").strip()
    if not pid:
        return
    pk_col = camel_partner_pk_column()
    now = datetime.now(timezone.utc).isoformat()

    invs = _fetch_all_investments_as_agent(pid)

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

    lineage = downline_partner_ids_including_self(pid)
    total_business = _sum_principal_for_agent_ids(lineage)

    self_earn_paid = 0.0
    team_earn_paid = 0.0
    commission_pending = 0.0
    nm_lo, nm_hi = next_month_bounds_utc()
    upcoming_next_month = 0.0
    commission_rows = _fetch_all_commission_lines_for_beneficiary(pid)
    for row in commission_rows:
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
            pd = parse_timestamptz(row.get("payoutDate"))
            if pd is not None and nm_lo <= pd <= nm_hi:
                upcoming_next_month += a

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
        "participantInvestedTotal": round(participant_invested, 2),
        "introducerCommissionAmount": introducer_amt,
        "selfEarningAmount": round(self_earn_paid, 2),
        "teamEarningAmount": round(team_earn_paid, 2),
        "totalDeals": int(total_deals),
        "totalTeamMembers": int(total_team_members),
        "totalBusiness": round(total_business, 2),
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
                "recalculate_partner_portfolio: update failed (run SQL for portfolio columns / totalBusiness?) %s: %s",
                pid,
                e,
            )
        else:
            logger.warning("recalculate_partner_portfolio: update failed for %s: %s", pid, e)
