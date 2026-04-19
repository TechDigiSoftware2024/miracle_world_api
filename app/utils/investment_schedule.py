"""
Payment schedule math (aligned with Flutter _calculateNextPayoutAndSchedule).

First month is prorated by days remaining in the investment month; middle months full;
last month absorbs rounding remainder.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

try:
    from dateutil.relativedelta import relativedelta
except ImportError:  # pragma: no cover
    relativedelta = None  # type: ignore[misc, assignment]


def _r(v: float) -> float:
    return round(float(v), 2)


def calculate_payment_schedule(
    investment_date: datetime,
    monthly_return: float,
    duration: int,
) -> tuple[list[dict[str, Any]], Optional[datetime], float]:
    """
    Returns (schedule_rows_for_db, next_payout_date, next_payout_amount).
    Each row: monthNumber, amount, payoutDate (datetime), status 'pending'.
    """
    if relativedelta is None:
        raise RuntimeError("python-dateutil is required for investment schedules")

    if duration <= 0 or monthly_return <= 0:
        return [], None, 0.0

    if investment_date.tzinfo is None:
        investment_date = investment_date.replace(tzinfo=timezone.utc)

    base = investment_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Last day of investment calendar month
    if base.month == 12:
        next_month_start = base.replace(year=base.year + 1, month=1, day=1)
    else:
        next_month_start = base.replace(month=base.month + 1, day=1)
    last_day_of_investment_month = next_month_start - timedelta(days=1)
    total_days_in_month = last_day_of_investment_month.day
    covered_days = total_days_in_month - investment_date.day + 1

    mr = float(monthly_return)
    first_payout_amount = _r((mr / total_days_in_month) * covered_days)
    remaining_amount = _r(mr - first_payout_amount)

    first_payout_date = base + relativedelta(months=1)

    schedule: list[dict[str, Any]] = []

    if duration == 1:
        schedule.append({
            "monthNumber": 1,
            "amount": _r(mr),
            "payoutDate": first_payout_date,
            "status": "pending",
        })
    else:
        schedule.append({
            "monthNumber": 1,
            "amount": first_payout_amount,
            "payoutDate": first_payout_date,
            "status": "pending",
        })
        for i in range(1, duration - 1):
            payout_date = base + relativedelta(months=i + 1)
            schedule.append({
                "monthNumber": i + 1,
                "amount": _r(mr),
                "payoutDate": payout_date,
                "status": "pending",
            })
        last_payout_date = base + relativedelta(months=duration)
        schedule.append({
            "monthNumber": duration,
            "amount": _r(mr + remaining_amount),
            "payoutDate": last_payout_date,
            "status": "pending",
        })

    next_payout = schedule[0]["payoutDate"]
    next_amt = float(schedule[0]["amount"])
    return schedule, next_payout, next_amt


def schedule_rows_to_db(
    investment_id: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        pd = r["payoutDate"]
        if isinstance(pd, datetime):
            pds = pd.isoformat()
        else:
            pds = str(pd)
        out.append({
            "investmentId": investment_id,
            "monthNumber": r["monthNumber"],
            "payoutDate": pds,
            "amount": r["amount"],
            "status": r["status"],
        })
    return out
