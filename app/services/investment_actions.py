"""Regenerate payment schedule rows when an investment becomes Active."""

from datetime import datetime, timezone

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.utils.investment_schedule import calculate_payment_schedule, schedule_rows_to_db

_TABLE_PS = "payment_schedules"


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
