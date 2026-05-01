"""Generate partner commission schedule rows when an investment becomes Active."""

from datetime import datetime, timezone
from typing import Any, Optional

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.utils.db_column_names import camel_partner_pk_column
from app.utils.investment_schedule import calculate_payment_schedule

_TABLE = "partner_commission_schedules"


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


def _commission_hops(agent_id: str) -> list[dict[str, Any]]:
    """
    Build beneficiary × snapshotted rate for each month.

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
    level = 1
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
                "level": level,
                "ratePercent": ic,
            })
        next_row = _fetch_partner(parent_id, cache, pk_col)
        if not next_row:
            break
        curr_row = next_row
        level += 1

    return hops


def replace_partner_commission_schedules(
    investment_id: str,
    investment_row: dict,
    investment_start: datetime,
) -> None:
    """
    Replace all commission lines for this investment: same months/payout dates as participant
    payment_schedules; amount = investedAmount × ratePercent / 100 per line per month.
    """
    iid = str(investment_id or "").strip()
    if not iid:
        return

    delete_partner_commission_schedules(iid)

    monthly = float(investment_row.get("monthlyPayout") or 0)
    duration = int(investment_row.get("durationMonths") or 0)
    invested = float(investment_row.get("investedAmount") or 0)
    agent_id = str(investment_row.get("agentId") or "").strip()

    schedule_rows, _, _ = calculate_payment_schedule(investment_start, monthly, duration)
    if not schedule_rows or invested <= 0:
        return

    hops = _commission_hops(agent_id)
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

        for hop in hops:
            rate = float(hop["ratePercent"])
            amt = round(invested * rate / 100.0, 2)
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
