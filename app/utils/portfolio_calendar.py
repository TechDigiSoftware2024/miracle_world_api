"""UTC calendar windows for portfolio fields (e.g. upcoming next-month payment)."""

import calendar
from datetime import datetime, timezone
from typing import Any, Optional


def parse_timestamptz(value: Any) -> Optional[datetime]:
    """Parse DB / JSON timestamp to timezone-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def next_month_bounds_utc(now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """First instant and last instant (inclusive) of the **next** calendar month in UTC."""
    n = now or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    n = n.astimezone(timezone.utc)
    y, m = n.year, n.month
    if m == 12:
        ny, nm = y + 1, 1
    else:
        ny, nm = y, m + 1
    start = datetime(ny, nm, 1, 0, 0, 0, tzinfo=timezone.utc)
    last_d = calendar.monthrange(ny, nm)[1]
    end = datetime(ny, nm, last_d, 23, 59, 59, tzinfo=timezone.utc)
    return start, end
