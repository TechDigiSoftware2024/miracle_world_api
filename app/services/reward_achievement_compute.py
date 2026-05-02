"""
Compute reward-program achievement: paid partner_commission_schedules in [start, end],
split direct (level 0) vs team (level >= 1), vs program goal (DIRECT / TEAM / combined).
"""

from __future__ import annotations

import calendar
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.utils.db_column_names import camel_partner_pk_column

logger = logging.getLogger(__name__)

_TABLE_ACH = "reward_program_achievements"
_TABLE_PROG = "reward_programs"
_TABLE_PC = "partner_commission_schedules"


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


def sum_paid_commission_direct_team(
    partner_id: str,
    lo: datetime,
    hi: datetime,
) -> tuple[float, float]:
    """
    Sum **paid** commission lines for beneficiary in [lo, hi] inclusive (UTC).
    """
    pid = str(partner_id or "").strip()
    if not pid:
        return 0.0, 0.0
    lo_s = lo.astimezone(timezone.utc).isoformat()
    hi_s = hi.astimezone(timezone.utc).isoformat()
    direct = 0.0
    team = 0.0
    try:
        res = (
            supabase.table(_TABLE_PC)
            .select("amount,level")
            .eq("beneficiaryPartnerId", pid)
            .eq("status", "paid")
            .gte("payoutDate", lo_s)
            .lte("payoutDate", hi_s)
            .execute()
        )
        for row in res.data or []:
            a = _f(row.get("amount"))
            lv = int(row.get("level") or 0)
            if lv <= 0:
                direct += a
            else:
                team += a
    except APIError as e:
        logger.warning("sum_paid_commission_direct_team: %s", e)
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
    previous_goal_reached: Optional[bool] = None,
    previous_achieved_at: Optional[str] = None,
) -> dict[str, Any]:
    g_rupees = goal_amount_rupees(
        _f(program.get("goalAmountValue")),
        str(program.get("goalAmountUnit") or "LAKH"),
    )
    d_tot, t_tot = sum_paid_commission_direct_team(partner_id, lo, hi)
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
    out: list[dict[str, Any]] = []
    if ptype == "ULTIMATE":
        row = build_progress_row(program, pid, "FULL", start, end)
        row.pop("computedAt", None)
        out.append(row)
    elif ptype == "MONTHLY":
        for pk, lo, hi in iter_month_windows_utc(start, end):
            row = build_progress_row(program, pid, pk, lo, hi)
            row.pop("computedAt", None)
            out.append(row)
    else:
        row = build_progress_row(program, pid, "FULL", start, end)
        row.pop("computedAt", None)
        out.append(row)
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

    rows_to_insert: list[dict[str, Any]] = []
    for pid in partner_ids:
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
