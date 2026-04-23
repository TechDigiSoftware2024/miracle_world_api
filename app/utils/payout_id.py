"""Sequential payout ids: MWPOT000001, MWPOT000002, … (max 20 chars)."""

from postgrest.exceptions import APIError

from app.db.database import supabase

_PREFIX = "MWPOT"
_WIDTH = 6
_TABLE = "payouts"
_PK = "payoutId"


def new_payout_id() -> str:
    next_n = 1
    try:
        result = (
            supabase.table(_TABLE)
            .select(_PK)
            .like(_PK, f"{_PREFIX}%")
            .order(_PK, desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            last = (result.data[0] or {}).get(_PK) or ""
            if last.startswith(_PREFIX):
                suffix = last[len(_PREFIX) :]
                if suffix.isdigit():
                    next_n = int(suffix) + 1
    except APIError:
        next_n = 1

    return f"{_PREFIX}{next_n:0{_WIDTH}d}"
