from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.utils.supabase_errors import format_api_error

_TABLE = "payouts"


def _safe_search_fragment(q: str) -> str:
    return "".join(c for c in (q or "").strip() if c not in "*,()")


def fetch_payout_rows(
    supabase: Client,
    *,
    user_id: Optional[str] = None,
    recipient_type: Optional[str] = None,
    q: Optional[str] = None,
    status: Optional[str] = None,
    payout_type: Optional[str] = None,
    payment_method: Optional[str] = None,
    payout_date_from: Optional[datetime] = None,
    payout_date_to: Optional[datetime] = None,
    level_depth: Optional[int] = None,
) -> List[dict]:
    try:
        query = supabase.table(_TABLE).select("*")
        if user_id is not None and str(user_id).strip():
            query = query.eq("userId", str(user_id).strip())
        if recipient_type is not None and str(recipient_type).strip():
            query = query.eq("recipientType", str(recipient_type).strip())
        if status is not None and str(status).strip():
            query = query.eq("status", str(status).strip())
        if payout_type is not None and str(payout_type).strip():
            query = query.eq("payoutType", str(payout_type).strip())
        if payment_method is not None and str(payment_method).strip():
            query = query.eq("paymentMethod", str(payment_method).strip())
        if payout_date_from is not None:
            query = query.gte("payoutDate", payout_date_from.isoformat())
        if payout_date_to is not None:
            query = query.lte("payoutDate", payout_date_to.isoformat())
        if level_depth is not None:
            query = query.eq("levelDepth", int(level_depth))

        inner = _safe_search_fragment(q or "")
        if inner:
            pat = f"*{inner}*"
            query = query.or_(
                f"payoutId.ilike.{pat},"
                f"userId.ilike.{pat},"
                f"transactionId.ilike.{pat},"
                f"remarks.ilike.{pat},"
                f"investmentId.ilike.{pat}"
            )

        result = query.order("payoutDate", desc=True).order("createdAt", desc=True).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return list(result.data or [])
