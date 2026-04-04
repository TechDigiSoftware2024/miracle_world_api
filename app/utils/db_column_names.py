"""Resolve actual PostgREST column names (new vs legacy Supabase schemas)."""

from functools import lru_cache

from postgrest.exceptions import APIError

from app.db.database import supabase


def _is_missing_column_error(exc: APIError) -> bool:
    raw = exc.args[0] if exc.args else {}
    if isinstance(raw, dict):
        return raw.get("code") == "42703"
    return "does not exist" in str(exc).lower()


@lru_cache(maxsize=1)
def camel_participant_pk_column() -> str:
    try:
        supabase.table("participants").select("participantId").limit(1).execute()
        return "participantId"
    except APIError as e:
        if _is_missing_column_error(e):
            supabase.table("participants").select("investorId").limit(1).execute()
            return "investorId"
        raise


@lru_cache(maxsize=1)
def camel_partner_pk_column() -> str:
    try:
        supabase.table("partners").select("partnerId").limit(1).execute()
        return "partnerId"
    except APIError as e:
        if _is_missing_column_error(e):
            supabase.table("partners").select("agentId").limit(1).execute()
            return "agentId"
        raise
