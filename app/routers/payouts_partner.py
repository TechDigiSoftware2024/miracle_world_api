from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.payout import PayoutResponse
from app.utils.payout_query import fetch_payout_rows

router = APIRouter(prefix="/payouts", tags=["Partner", "Payouts"])


@router.get("", response_model=List[PayoutResponse])
def partner_list_payouts(
    q: Optional[str] = Query(None, description="Search payout id, investment, txn id, remarks"),
    payout_status: Optional[str] = Query(None, description="Filter by status", alias="payoutStatus"),
    payout_type: Optional[str] = Query(None, description="Filter by payoutType", alias="payoutType"),
    payment_method: Optional[str] = Query(
        None, description="Filter by paymentMethod (BANK, IMPS/NEFT, CASH)", alias="paymentMethod"
    ),
    payout_date_from: Optional[datetime] = Query(None, alias="payoutDateFrom"),
    payout_date_to: Optional[datetime] = Query(None, alias="payoutDateTo"),
    level_depth: Optional[int] = Query(
        None,
        ge=1,
        le=100,
        description="MLM downline level filter",
        alias="levelDepth",
    ),
    current_user: dict = Depends(require_role(["partner"])),
):
    uid = str(current_user.get("userId", "")).strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token is missing userId",
        )
    rows = fetch_payout_rows(
        supabase,
        user_id=uid,
        recipient_type="partner",
        q=q,
        status=payout_status,
        payout_type=payout_type,
        payment_method=payment_method,
        payout_date_from=payout_date_from,
        payout_date_to=payout_date_to,
        level_depth=level_depth,
    )
    return [PayoutResponse.model_validate(r) for r in rows]
