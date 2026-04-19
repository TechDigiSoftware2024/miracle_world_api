"""Sequential investment ids: MWINV000001, MWINV000002, … (max 20 chars).

Payment schedule rows use the DB ``payment_schedules.id`` (integer, no prefix) and
``monthNumber`` starting at 1 — see ``app.utils.investment_schedule``.
"""

from postgrest.exceptions import APIError

from app.db.database import supabase

_PREFIX = "MWINV"
_WIDTH = 6
_TABLE = "investments"


def new_investment_id() -> str:
    next_n = 1
    try:
        result = (
            supabase.table(_TABLE)
            .select("investmentId")
            .like("investmentId", f"{_PREFIX}%")
            .order("investmentId", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            last = (result.data[0] or {}).get("investmentId") or ""
            if last.startswith(_PREFIX):
                suffix = last[len(_PREFIX) :]
                if suffix.isdigit():
                    next_n = int(suffix) + 1
    except APIError:
        next_n = 1

    return f"{_PREFIX}{next_n:0{_WIDTH}d}"
