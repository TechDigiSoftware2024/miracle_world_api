"""
Payment schedule math for investments.

The **monthly** cash amount ``M`` is whatever is stored on the investment as
``monthlyPayout`` (e.g. ₹1,00,000 at 10%/month total payout ⇒ ``M = 10_000``,
whether that 10% is labelled as 5% profit + 5% capital in fund terms or not).

**Anchor date:** schedules use the investment **activation** instant passed in
(typically ``investmentStartDate`` when status becomes Active).

**Full-month start (day = 1):** every payout on subsequent month-1sts equals ``M``.

**Mid-month start:** first payout (on the **next** month's 1st) is pro-rata for the
partial calendar month of activation:

- ``remaining_days = days_in_month(anchor) - anchor.day + 1``
- ``per_day = M / days_in_month(anchor)`` (stored rounded to 2 dp on the row)
- ``first = round_half_up(per_day * remaining_days)``

Middle months: full ``M`` each. **Last** month closes the ledger so totals match
``duration × M``:

``last = M + (M - first) = 2 * M - first``

Example (April 30 days, activate 10th, ``M = 10_000``): remaining 21 days,
``first ≈ 7_000``; last installment ``10_000 + 3_000 = 13_000`` (the ₹3_000 is
the slice of the first calendar month that was not paid in the pro-rata line).

Uses :class:`decimal.Decimal` with half-up quantization to 2 dp; DB uses NUMERIC.
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

try:
    from dateutil.relativedelta import relativedelta
except ImportError:  # pragma: no cover
    relativedelta = None  # type: ignore[misc, assignment]

_TWO_DP = Decimal("0.01")


def _q2(x: Decimal) -> Decimal:
    return x.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def _days_in_month(d: datetime) -> int:
    if d.month == 12:
        next_month_start = d.replace(year=d.year + 1, month=1, day=1)
    else:
        next_month_start = d.replace(month=d.month + 1, day=1)
    last_day = next_month_start - timedelta(days=1)
    return last_day.day


def calculate_payment_schedule(
    investment_date: datetime,
    monthly_return: float,
    duration: int,
) -> tuple[list[dict[str, Any]], Optional[datetime], float]:
    """
    Returns (schedule_rows, next_payout_date, next_payout_amount).

    Each row: monthNumber, amount (float, 2 dp), payoutDate, status 'pending',
    lineType ('full' | 'prorata' | 'adjustment'), isProrata, optional daysCount /
    perDayAmount for the pro-rata line.
    """
    if relativedelta is None:
        raise RuntimeError("python-dateutil is required for investment schedules")

    if duration <= 0 or monthly_return <= 0:
        return [], None, 0.0

    if investment_date.tzinfo is None:
        investment_date = investment_date.replace(tzinfo=timezone.utc)

    base = investment_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    M = _q2(Decimal(str(monthly_return)))
    start_day = investment_date.day

    schedule: list[dict[str, Any]] = []

    if start_day == 1:
        # Case 1: every installment is the full monthly amount
        for m in range(1, duration + 1):
            payout_date = base + relativedelta(months=m)
            schedule.append({
                "monthNumber": m,
                "amount": float(M),
                "payoutDate": payout_date,
                "status": "pending",
                "lineType": "full",
                "isProrata": False,
                "daysCount": None,
                "perDayAmount": None,
            })
    else:
        # Case 2: pro-rata first month slice, full middles, last = M + (M - first_pro_rata)
        total_days = _days_in_month(investment_date)
        remaining_days = total_days - start_day + 1
        per_day = M / Decimal(total_days)
        per_day_q = _q2(per_day)
        first_pro_rata = _q2(per_day * Decimal(remaining_days))
        # last = M + (M − first) so sum of N lines = N × M; "adjustment" is the deferred slice
        last_amount = _q2(Decimal(2) * M - first_pro_rata)

        first_payout_date = base + relativedelta(months=1)

        if duration == 1:
            # Single installment: only the pro-rata slice for the partial first period
            schedule.append({
                "monthNumber": 1,
                "amount": float(first_pro_rata),
                "payoutDate": first_payout_date,
                "status": "pending",
                "lineType": "prorata",
                "isProrata": True,
                "daysCount": remaining_days,
                "perDayAmount": float(per_day_q),
            })
        else:
            schedule.append({
                "monthNumber": 1,
                "amount": float(first_pro_rata),
                "payoutDate": first_payout_date,
                "status": "pending",
                "lineType": "prorata",
                "isProrata": True,
                "daysCount": remaining_days,
                "perDayAmount": float(per_day_q),
            })
            for m in range(2, duration):
                payout_date = base + relativedelta(months=m)
                schedule.append({
                    "monthNumber": m,
                    "amount": float(M),
                    "payoutDate": payout_date,
                    "status": "pending",
                    "lineType": "full",
                    "isProrata": False,
                    "daysCount": None,
                    "perDayAmount": None,
                })
            last_payout_date = base + relativedelta(months=duration)
            schedule.append({
                "monthNumber": duration,
                "amount": float(last_amount),
                "payoutDate": last_payout_date,
                "status": "pending",
                "lineType": "adjustment",
                "isProrata": False,
                "daysCount": None,
                "perDayAmount": None,
            })

    next_payout = schedule[0]["payoutDate"]
    next_amt = float(schedule[0]["amount"])
    return schedule, next_payout, next_amt


def schedule_rows_to_db(
    investment_id: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Persist schedule lines. ``monthNumber`` is always 1, 2, 3, … (no string prefix).
    Row ``id`` is assigned by the database (SERIAL/IDENTITY).
    """
    out = []
    for idx, r in enumerate(rows, start=1):
        pd = r["payoutDate"]
        if isinstance(pd, datetime):
            pds = pd.isoformat()
        else:
            pds = str(pd)
        row_db: dict[str, Any] = {
            "investmentId": investment_id,
            "monthNumber": idx,
            "payoutDate": pds,
            "amount": r["amount"],
            "status": r["status"],
            "lineType": r.get("lineType", "full"),
            "isProrata": bool(r.get("isProrata", False)),
            "daysCount": r.get("daysCount"),
            "perDayAmount": r.get("perDayAmount"),
        }
        out.append(row_db)
    return out
