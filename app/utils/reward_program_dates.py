"""Compute reward program end date from start + goal window (days)."""

from datetime import datetime, timedelta, timezone


def compute_end_date(start_date: datetime, goal_days: int) -> datetime:
    start = start_date
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return start + timedelta(days=int(goal_days))
