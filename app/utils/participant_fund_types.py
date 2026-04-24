"""Fund types visible to a participant: all active non-special funds, plus assigned special funds when eligible."""

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.utils.db_column_names import camel_participant_pk_column

_FTABLE = "fund_types"
_JUNCTION = "participant_special_funds"


def enrich_participant_row_with_special_fund_ids(row: dict, participant_id: str) -> dict:
    """Attach eligibleSpecialFundIds and default isEligible for API responses."""
    out = dict(row)
    uid = str(participant_id or "").strip()
    try:
        jr = (
            supabase.table(_JUNCTION)
            .select("fundTypeId")
            .eq("participantId", uid)
            .execute()
        )
        fund_ids = sorted({int(r["fundTypeId"]) for r in (jr.data or [])})
    except APIError:
        fund_ids = []
    out["eligibleSpecialFundIds"] = fund_ids
    if out.get("isEligible") is None:
        out["isEligible"] = False
    return out


def fetch_visible_fund_type_rows(participant_id: str) -> list[dict]:
    pid = str(participant_id or "").strip()
    if not pid:
        return []

    pid_col = camel_participant_pk_column()
    try:
        pr = (
            supabase.table("participants")
            .select(f'{pid_col},"isEligible"')
            .eq(pid_col, pid)
            .limit(1)
            .execute()
        )
    except APIError:
        return []

    elig = bool(pr.data[0].get("isEligible")) if pr.data else False

    try:
        all_res = (
            supabase.table(_FTABLE)
            .select("*")
            .eq("status", "active")
            .order("createdAt", desc=True)
            .execute()
        )
    except APIError:
        return []

    rows = all_res.data or []
    if not elig:
        return [r for r in rows if not r.get("isSpecial")]

    try:
        jres = (
            supabase.table(_JUNCTION)
            .select("fundTypeId")
            .eq("participantId", pid)
            .execute()
        )
    except APIError:
        return [r for r in rows if not r.get("isSpecial")]

    allowed_special = {int(x["fundTypeId"]) for x in (jres.data or [])}
    out: list[dict] = []
    for r in rows:
        fid = int(r["id"])
        if not r.get("isSpecial"):
            out.append(r)
        elif fid in allowed_special:
            out.append(r)
    return out
