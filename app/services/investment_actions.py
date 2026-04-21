"""Regenerate payment schedule rows when an investment becomes Active."""

from datetime import datetime, timezone

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.utils.investment_schedule import calculate_payment_schedule, schedule_rows_to_db

_TABLE_INV = "investments"
_TABLE_PS = "payment_schedules"


def sync_investment_status_with_payment_lines(investment_id: str) -> None:
    """
    When all schedule lines are paid, set investment to Matured.
    If a line is un-paid again after Matured, set back to Active and refresh nextPayoutDate.
    """
    inv_res = (
        supabase.table(_TABLE_INV).select("*").eq("investmentId", investment_id).execute()
    )
    if not inv_res.data:
        return
    inv = inv_res.data[0]
    st = str(inv.get("status") or "").strip()
    if st not in ("Active", "Matured"):
        return

    lines_res = (
        supabase.table(_TABLE_PS)
        .select("status,payoutDate")
        .eq("investmentId", investment_id)
        .execute()
    )
    lines = lines_res.data or []
    if not lines:
        return

    all_paid = all(str(x.get("status") or "").strip() == "paid" for x in lines)
    now = datetime.now(timezone.utc).isoformat()

    if all_paid and st == "Active":
        supabase.table(_TABLE_INV).update(
            {"status": "Matured", "nextPayoutDate": None, "updatedAt": now}
        ).eq("investmentId", investment_id).execute()
        return

    if not all_paid and st == "Matured":
        unpaid = [
            x
            for x in lines
            if str(x.get("status") or "").strip() != "paid"
        ]
        unpaid.sort(key=lambda x: str(x.get("payoutDate") or ""))
        next_iso = unpaid[0].get("payoutDate") if unpaid else None
        supabase.table(_TABLE_INV).update(
            {"status": "Active", "nextPayoutDate": next_iso, "updatedAt": now}
        ).eq("investmentId", investment_id).execute()


def replace_payment_schedules(
    investment_id: str,
    investment_row: dict,
    investment_start: datetime,
) -> str | None:
    """
    Deletes existing schedule lines and inserts new ones. Returns nextPayoutDate ISO or None.
    """
    monthly = float(investment_row.get("monthlyPayout") or 0)
    duration = int(investment_row.get("durationMonths") or 0)
    rows, next_pd, _ = calculate_payment_schedule(investment_start, monthly, duration)
    try:
        supabase.table(_TABLE_PS).delete().eq("investmentId", investment_id).execute()
    except APIError:
        raise
    if not rows:
        return None
    now = datetime.now(timezone.utc).isoformat()
    db_rows = schedule_rows_to_db(investment_id, rows)
    for r in db_rows:
        r["createdAt"] = now
        r["updatedAt"] = None
        supabase.table(_TABLE_PS).insert(r).execute()
    return next_pd.isoformat() if next_pd else None
