"""
Reward-program achievement: **invested principal** (eligible business) in each period vs goal.

- **Direct**: sum of ``investedAmount`` where the partner is the deal ``agentId`` and
  ``investmentDate`` falls in the period (qualifying investment statuses only).
- **Team**: sum of principal on downline partners' deals only when the partner would receive a
  **level ≥ 1** commission slot for that deal agent — i.e. same rules as ``commission_hops_for_agent``:
  if a child's ``introducerCommission`` is 0, that business counts toward the child's **direct**
  progress only, not the introducer's **team** bucket.
"""

from __future__ import annotations

import calendar
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.services.partner_commission_schedule import commission_hops_for_agent
from app.utils.db_column_names import camel_partner_pk_column
from app.utils.partner_team import downline_partner_ids_including_self

logger = logging.getLogger(__name__)

_TABLE_ACH = "reward_program_achievements"
_TABLE_PROG = "reward_programs"
_TABLE_INV = "investments"

_QUALIFYING_STATUSES = ("Active", "Matured", "Completed", "Pending Approval")

# PostgREST default cap; paginate
_PAGE = 1000


def _f(x: Any) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_ts(val: Any) -> datetime:
    if isinstance(val, datetime):
        d = val
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(val).replace("Z", "+00:00"))


def goal_amount_rupees(goal_value: float, goal_unit: str) -> float:
    u = (goal_unit or "LAKH").strip().upper()
    mult = 100_000.0 if u == "LAKH" else 10_000_000.0
    return round(_f(goal_value) * mult, 2)


def qualifying_amount(direct: float, team: float, business_type: Optional[str]) -> float:
    bt = (business_type or "").strip().upper() if business_type else ""
    if bt == "DIRECT":
        return round(direct, 2)
    if bt == "TEAM":
        return round(team, 2)
    return round(direct + team, 2)


def _investment_date_in_range(row: dict, lo: datetime, hi: datetime) -> bool:
    try:
        dt = _parse_ts(row.get("investmentDate"))
        dt = dt.astimezone(timezone.utc)
        lo_u = lo.astimezone(timezone.utc)
        hi_u = hi.astimezone(timezone.utc)
        return lo_u <= dt <= hi_u
    except (TypeError, ValueError):
        return False


def fetch_investments_by_agent_in_window(lo: datetime, hi: datetime) -> dict[str, list[dict]]:
    """All qualifying investments with ``investmentDate`` in [``lo``, ``hi``], grouped by ``agentId``."""
    lo_s = lo.astimezone(timezone.utc).isoformat()
    hi_s = hi.astimezone(timezone.utc).isoformat()
    st_list = list(_QUALIFYING_STATUSES)
    by_agent: dict[str, list[dict]] = {}
    off = 0
    while True:
        try:
            res = (
                supabase.table(_TABLE_INV)
                .select("investmentId,agentId,investedAmount,status,investmentDate")
                .gte("investmentDate", lo_s)
                .lte("investmentDate", hi_s)
                .in_("status", st_list)
                .order("investmentId")
                .range(off, off + _PAGE - 1)
                .execute()
            )
        except APIError as e:
            logger.warning("fetch_investments_by_agent_in_window: %s", e)
            break
        chunk = list(res.data or [])
        if not chunk:
            break
        for row in chunk:
            aid = str(row.get("agentId") or "").strip()
            if aid:
                by_agent.setdefault(aid, []).append(row)
        if len(chunk) < _PAGE:
            break
        off += _PAGE
    return by_agent


def _upline_beneficiaries_ge1(agent_id: str, cache: dict[str, set[str]]) -> set[str]:
    """Partners who get a level ≥ 1 commission hop from deals where ``agent_id`` is the agent."""
    aid = str(agent_id or "").strip()
    if not aid:
        return set()
    if aid not in cache:
        hops = commission_hops_for_agent(aid)
        cache[aid] = {
            str(h.get("beneficiaryPartnerId") or "").strip()
            for h in hops
            if int(h.get("level") or 0) >= 1
        }
    return cache[aid]


def sum_direct_team_business_in_period(
    partner_id: str,
    lo: datetime,
    hi: datetime,
    by_agent: dict[str, list[dict]],
    lineage: list[str],
    upline_cache: dict[str, set[str]],
) -> tuple[float, float]:
    """(direct principal, team principal) attributed in [lo, hi] (UTC-inclusive on investmentDate)."""
    pid = str(partner_id or "").strip()
    if not pid:
        return 0.0, 0.0
    direct = 0.0
    for row in by_agent.get(pid, []):
        if _investment_date_in_range(row, lo, hi):
            direct += _f(row.get("investedAmount"))
    team = 0.0
    for d in lineage:
        if d == pid:
            continue
        if pid not in _upline_beneficiaries_ge1(d, upline_cache):
            continue
        for row in by_agent.get(d, []):
            if _investment_date_in_range(row, lo, hi):
                team += _f(row.get("investedAmount"))
    return round(direct, 2), round(team, 2)


def iter_month_windows_utc(prog_start: datetime, prog_end: datetime):
    """Yield (period_key YYYY-MM, clipped_lo, clipped_hi) for each UTC month overlapping the program."""
    a = _parse_ts(prog_start)
    b = _parse_ts(prog_end)
    if a > b:
        return
    y, m = a.year, a.month
    while True:
        first = datetime(y, m, 1, 0, 0, 0, tzinfo=timezone.utc)
        last_d = calendar.monthrange(y, m)[1]
        last = datetime(y, m, last_d, 23, 59, 59, tzinfo=timezone.utc)
        if first > b:
            break
        lo = max(a, first)
        hi = min(b, last)
        if lo <= hi:
            yield f"{y:04d}-{m:02d}", lo, hi
        if y == b.year and m == b.month:
            break
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1


def build_progress_row(
    program: dict,
    partner_id: str,
    period_key: str,
    lo: datetime,
    hi: datetime,
    by_agent: dict[str, list[dict]],
    lineage: list[str],
    upline_cache: dict[str, set[str]],
    previous_goal_reached: Optional[bool] = None,
    previous_achieved_at: Optional[str] = None,
) -> dict[str, Any]:
    g_rupees = goal_amount_rupees(
        _f(program.get("goalAmountValue")),
        str(program.get("goalAmountUnit") or "LAKH"),
    )
    d_tot, t_tot = sum_direct_team_business_in_period(
        partner_id, lo, hi, by_agent, lineage, upline_cache
    )
    qual = qualifying_amount(
        d_tot,
        t_tot,
        program.get("businessType"),
    )
    reached = qual >= g_rupees - 0.01  # float tolerance 1 paisa
    now = datetime.now(timezone.utc).isoformat()
    achieved_at: Optional[str] = None
    if reached:
        if previous_goal_reached and previous_achieved_at:
            achieved_at = previous_achieved_at
        else:
            achieved_at = now
    return {
        "programId": int(program["id"]),
        "partnerId": partner_id,
        "periodKey": period_key,
        "periodStart": lo.astimezone(timezone.utc).isoformat(),
        "periodEnd": hi.astimezone(timezone.utc).isoformat(),
        "directPaidInPeriod": d_tot,
        "teamPaidInPeriod": t_tot,
        "qualifyingAmount": qual,
        "goalAmountRupees": g_rupees,
        "goalReached": reached,
        "achievedAt": achieved_at,
        "computedAt": now,
    }


def compute_progress_for_partner_program(program: dict, partner_id: str) -> list[dict[str, Any]]:
    """Live progress rows for API (no DB write)."""
    pid = str(partner_id or "").strip()
    if not pid:
        return []
    ptype = str(program.get("programType") or "").strip().upper()
    start = _parse_ts(program.get("startDate"))
    end = _parse_ts(program.get("endDate"))
    by_agent = fetch_investments_by_agent_in_window(start, end)
    lineage = downline_partner_ids_including_self(pid)
    upline_cache: dict[str, set[str]] = {}
    out: list[dict[str, Any]] = []
    if ptype == "ULTIMATE":
        row = build_progress_row(
            program, pid, "FULL", start, end, by_agent, lineage, upline_cache
        )
        row.pop("computedAt", None)
        out.append(row)
    elif ptype == "MONTHLY":
        for pk, lo, hi in iter_month_windows_utc(start, end):
            row = build_progress_row(program, pid, pk, lo, hi, by_agent, lineage, upline_cache)
            row.pop("computedAt", None)
            out.append(row)
    else:
        row = build_progress_row(
            program, pid, "FULL", start, end, by_agent, lineage, upline_cache
        )
        row.pop("computedAt", None)
        out.append(row)
    return out


def list_active_non_expired_programs(now: Optional[datetime] = None) -> list[dict]:
    """
    Active reward programs that are still valid as of ``now``.
    Programs past ``endDate`` are excluded.
    """
    n = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        res = (
            supabase.table(_TABLE_PROG)
            .select("*")
            .eq("isActive", True)
            .gte("endDate", n.isoformat())
            .order("goalAmountValue")
            .execute()
        )
    except APIError:
        return []
    return list(res.data or [])


def upsert_partner_achievement_rows_for_program(program: dict, partner_id: str) -> int:
    """
    Compute and persist all achievement slices for one (program, partner) pair.
    Existing rows for this pair are replaced.
    """
    pid = str(partner_id or "").strip()
    if not pid:
        return 0
    prog_id = int(program.get("id") or 0)
    if prog_id <= 0:
        return 0
    rows = compute_progress_for_partner_program(program, pid)
    if not rows:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    db_rows: list[dict[str, Any]] = []
    for r in rows:
        db_rows.append({
            **r,
            "programId": prog_id,
            "partnerId": pid,
            "computedAt": now,
        })
    try:
        supabase.table(_TABLE_ACH).delete().eq("programId", prog_id).eq("partnerId", pid).execute()
        supabase.table(_TABLE_ACH).insert(db_rows).execute()
    except APIError:
        return 0
    return len(db_rows)


def initialize_partner_reward_achievements(partner_id: str) -> int:
    """
    Seed persisted reward achievements for a newly created partner across all
    currently active/non-expired programs.
    """
    pid = str(partner_id or "").strip()
    if not pid:
        return 0
    programs = list_active_non_expired_programs()
    written = 0
    for p in programs:
        written += upsert_partner_achievement_rows_for_program(p, pid)
    return written


def recompute_partner_reward_achievements(partner_id: str) -> int:
    """
    Recompute persisted achievement rows for one partner across all active/non-expired programs.
    """
    return initialize_partner_reward_achievements(partner_id)


def fetch_partner_achievement_rows(partner_id: str, program_ids: list[int]) -> dict[int, list[dict]]:
    """
    Read persisted achievement rows grouped by programId for one partner.
    """
    pid = str(partner_id or "").strip()
    ids = [int(x) for x in program_ids if int(x) > 0]
    if not pid or not ids:
        return {}
    out: dict[int, list[dict]] = {}
    try:
        res = (
            supabase.table(_TABLE_ACH)
            .select("*")
            .eq("partnerId", pid)
            .in_("programId", ids)
            .order("periodEnd")
            .execute()
        )
    except APIError:
        return {}
    for r in res.data or []:
        pg = int(r.get("programId") or 0)
        if pg > 0:
            out.setdefault(pg, []).append(r)
    return out


def _prev_achieved_at_iso(prev_r: dict) -> Optional[str]:
    v = prev_r.get("achievedAt")
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat()
    return str(v)


def _fetch_previous_achievements_map(program_id: int) -> dict[tuple[str, str], dict]:
    """(partnerId, periodKey) -> row for achievedAt preservation."""
    out: dict[tuple[str, str], dict] = {}
    try:
        res = (
            supabase.table(_TABLE_ACH)
            .select("partnerId,periodKey,goalReached,achievedAt")
            .eq("programId", program_id)
            .execute()
        )
        for r in res.data or []:
            pid = str(r.get("partnerId") or "")
            pk = str(r.get("periodKey") or "")
            out[(pid, pk)] = r
    except APIError:
        pass
    return out


def recompute_program_achievements(program_id: int) -> int:
    """
    Delete stored rows for this program and rebuild from all partners.
    Preserves achievedAt when goal stays met; clears when goal no longer met.
    """
    try:
        prog_res = supabase.table(_TABLE_PROG).select("*").eq("id", program_id).limit(1).execute()
    except APIError as e:
        logger.warning("recompute_program_achievements: program %s: %s", program_id, e)
        return 0
    if not prog_res.data:
        return 0
    program = prog_res.data[0]
    prev = _fetch_previous_achievements_map(program_id)

    try:
        supabase.table(_TABLE_ACH).delete().eq("programId", program_id).execute()
    except APIError as e:
        logger.warning("recompute_program_achievements: delete: %s", e)
        return 0

    pk_col = camel_partner_pk_column()
    partner_ids: list[str] = []
    try:
        off = 0
        page = 500
        while True:
            pr = (
                supabase.table("partners")
                .select(pk_col)
                .range(off, off + page - 1)
                .execute()
            )
            chunk = pr.data or []
            if not chunk:
                break
            for r in chunk:
                pid = str(r.get(pk_col) or "").strip()
                if pid:
                    partner_ids.append(pid)
            if len(chunk) < page:
                break
            off += page
    except APIError as e:
        logger.warning("recompute_program_achievements: partners list: %s", e)
        return 0

    ptype = str(program.get("programType") or "").strip().upper()
    start = _parse_ts(program.get("startDate"))
    end = _parse_ts(program.get("endDate"))
    by_agent = fetch_investments_by_agent_in_window(start, end)
    upline_cache: dict[str, set[str]] = {}

    rows_to_insert: list[dict[str, Any]] = []
    for pid in partner_ids:
        lineage = downline_partner_ids_including_self(pid)
        if ptype == "MONTHLY":
            for period_key, lo, hi in iter_month_windows_utc(start, end):
                key = (pid, period_key)
                prev_r = prev.get(key) or {}
                row = build_progress_row(
                    program,
                    pid,
                    period_key,
                    lo,
                    hi,
                    by_agent,
                    lineage,
                    upline_cache,
                    previous_goal_reached=bool(prev_r.get("goalReached")),
                    previous_achieved_at=_prev_achieved_at_iso(prev_r),
                )
                rows_to_insert.append(row)
        else:
            key = (pid, "FULL")
            prev_r = prev.get(key) or {}
            row = build_progress_row(
                program,
                pid,
                "FULL",
                start,
                end,
                by_agent,
                lineage,
                upline_cache,
                previous_goal_reached=bool(prev_r.get("goalReached")),
                previous_achieved_at=_prev_achieved_at_iso(prev_r),
            )
            rows_to_insert.append(row)

    inserted = 0
    batch = 100
    for i in range(0, len(rows_to_insert), batch):
        chunk = rows_to_insert[i : i + batch]
        try:
            supabase.table(_TABLE_ACH).insert(chunk).execute()
            inserted += len(chunk)
        except APIError as e:
            logger.warning("recompute_program_achievements: insert batch: %s", e)
    return inserted
