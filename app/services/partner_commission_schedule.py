"""Generate partner commission schedule rows when an investment becomes Active."""

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.utils.db_column_names import camel_partner_pk_column
from app.utils.investment_schedule import calculate_payment_schedule

_TABLE = "partner_commission_schedules"
_TWO_DP = Decimal("0.01")


def _money2(x: Decimal) -> Decimal:
    return x.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def _commission_amount_for_schedule_line(
    invested: float,
    rate_percent: float,
    participant_line_amount: float,
    monthly_nominal: float,
) -> float:
    """
    Full-month commission accrual is ``invested × rate / 100``; scale by the same factor as the
    participant line vs nominal monthly ``M`` (prorata first month, adjustment last month).
    """
    m = _money2(Decimal(str(monthly_nominal)))
    if m <= 0:
        return 0.0
    line_amt = _money2(Decimal(str(float(participant_line_amount))))
    scale = line_amt / m
    base = _money2(Decimal(str(invested)) * Decimal(str(rate_percent)) / Decimal("100"))
    return float(_money2(base * scale))


def sync_partner_commission_status_for_month(
    investment_id: str,
    month_number: int,
    new_status: str,
) -> None:
    """
    Mirror participant ``payment_schedules.status`` onto every ``partner_commission_schedules``
    row for the same investment and month so partner portfolio (paid vs pending) stays accurate.
    """
    iid = str(investment_id or "").strip()
    if not iid:
        return
    try:
        mn = int(month_number)
    except (TypeError, ValueError):
        return
    if mn < 1:
        return
    st = str(new_status or "").strip().lower()
    if st not in ("pending", "due", "paid"):
        return
    now = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table(_TABLE).update({
            "status": st,
            "updatedAt": now,
        }).eq("investmentId", iid).eq("monthNumber", mn).execute()
    except APIError:
        pass


def delete_partner_commission_schedules(investment_id: str) -> None:
    iid = str(investment_id or "").strip()
    if not iid:
        return
    supabase.table(_TABLE).delete().eq("investmentId", iid).execute()


def _fetch_partner(
    partner_id: str,
    cache: dict[str, Optional[dict]],
    pk_col: str,
) -> Optional[dict]:
    pid = str(partner_id or "").strip()
    if not pid:
        return None
    if pid in cache:
        return cache[pid]
    try:
        res = supabase.table("partners").select("*").eq(pk_col, pid).limit(1).execute()
    except APIError:
        cache[pid] = None
        return None
    row = res.data[0] if res.data else None
    cache[pid] = row
    return row


def commission_hops_for_agent(agent_id: str) -> list[dict[str, Any]]:
    """
    Build beneficiary × rate for each upline slot on a deal (same rules as stored commission rows).

    Level 0: deal agent earns selfCommission % on principal per month.
    Each upline hop: child's introducerCommission % to their introducer (omit if rate ≤ 0).
    """
    aid = str(agent_id or "").strip()
    if not aid:
        return []
    pk_col = camel_partner_pk_column()
    cache: dict[str, Optional[dict]] = {}
    row_agent = _fetch_partner(aid, cache, pk_col)
    if not row_agent:
        return []

    hops: list[dict[str, Any]] = []
    self_r = float(row_agent.get("selfCommission") or 0)
    if self_r > 0:
        hops.append({
            "beneficiaryPartnerId": aid,
            "level": 0,
            "ratePercent": self_r,
        })

    curr_row = row_agent
    payable_level = 1
    seen: set[str] = {aid}

    while True:
        parent_id = str(curr_row.get("introducer") or "").strip()
        if not parent_id or parent_id in seen:
            break
        seen.add(parent_id)
        ic = float(curr_row.get("introducerCommission") or curr_row.get("commission") or 0)
        if ic > 0:
            hops.append({
                "beneficiaryPartnerId": parent_id,
                "level": payable_level,
                "ratePercent": ic,
            })
            payable_level += 1
        next_row = _fetch_partner(parent_id, cache, pk_col)
        if not next_row:
            break
        curr_row = next_row

    return hops


def replace_partner_commission_schedules(
    investment_id: str,
    investment_row: dict,
    investment_start: datetime,
    *,
    payment_schedule_rows: Optional[list[dict[str, Any]]] = None,
) -> None:
    """
    Replace all commission lines for this investment: same months/payout dates as participant
    ``payment_schedules`` (including prorata first line and closing adjustment when activation is
    mid-month). Each line amount is ``investedAmount × ratePercent / 100`` scaled by
    ``participant_line_amount / monthlyPayout`` so partner accrual matches participant schedule math.

    Pass ``payment_schedule_rows`` from :func:`replace_payment_schedules` to skip a duplicate
    schedule calculation. Portfolio recalculation is left to the caller after the investment row
    is persisted (so Active status and schedules stay consistent).
    """
    iid = str(investment_id or "").strip()
    if not iid:
        return

    delete_partner_commission_schedules(iid)

    monthly = float(investment_row.get("monthlyPayout") or 0)
    duration = int(investment_row.get("durationMonths") or 0)
    invested = float(investment_row.get("investedAmount") or 0)
    agent_id = str(investment_row.get("agentId") or "").strip()

    if payment_schedule_rows is not None:
        schedule_rows = payment_schedule_rows
    else:
        schedule_rows, _, _ = calculate_payment_schedule(
            investment_start, monthly, duration
        )
    if not schedule_rows or invested <= 0:
        return

    hops = commission_hops_for_agent(agent_id)
    if not hops:
        return

    now = datetime.now(timezone.utc).isoformat()
    source_partner_id = agent_id
    db_rows: list[dict[str, Any]] = []

    for sched_row in schedule_rows:
        mn = int(sched_row["monthNumber"])
        pd = sched_row["payoutDate"]
        if isinstance(pd, datetime):
            pds = pd.isoformat()
        else:
            pds = str(pd)

        line_participant_amt = float(sched_row.get("amount") or 0)
        for hop in hops:
            rate = float(hop["ratePercent"])
            amt = _commission_amount_for_schedule_line(
                invested, rate, line_participant_amt, monthly
            )
            if amt <= 0:
                continue
            db_rows.append({
                "investmentId": iid,
                "monthNumber": mn,
                "payoutDate": pds,
                "beneficiaryPartnerId": hop["beneficiaryPartnerId"],
                "sourcePartnerId": source_partner_id,
                "level": int(hop["level"]),
                "ratePercent": rate,
                "amount": amt,
                "status": "pending",
                "createdAt": now,
                "updatedAt": None,
            })

    if not db_rows:
        return
    supabase.table(_TABLE).insert(db_rows).execute()
