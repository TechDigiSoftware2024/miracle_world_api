from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.payout import PayoutResponse
from app.utils.db_column_names import camel_participant_pk_column, camel_partner_pk_column
from app.utils.payout_query import fetch_payout_rows
from app.utils.supabase_errors import format_api_error

router = APIRouter(tags=["Admin", "Payouts"])


def _participant_or_404(participant_id: str) -> None:
    pid = camel_participant_pk_column()
    try:
        r = supabase.table("participants").select(pid).eq(pid, participant_id).limit(1).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    if not r.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Participant not found",
        )


def _partner_or_404(partner_id: str) -> None:
    prid = camel_partner_pk_column()
    try:
        r = supabase.table("partners").select(prid).eq(prid, partner_id).limit(1).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    if not r.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partner not found",
        )


@router.get(
    "/participants/{participant_id}/payouts",
    response_model=List[PayoutResponse],
    summary="List payouts for a participant (admin detail view)",
    description="Returns all payouts for `recipientType=participant` and `userId=participantId`.",
)
def admin_list_payouts_for_participant(
    participant_id: str,
    q: Optional[str] = Query(None, description="Search payout id, investment, txn id, remarks"),
    payout_status: Optional[str] = Query(None, description="Filter by status", alias="payoutStatus"),
    payout_type: Optional[str] = Query(None, description="Filter by payoutType", alias="payoutType"),
    payment_method: Optional[str] = Query(
        None, description="Filter by paymentMethod (BANK, IMPS/NEFT, CASH)", alias="paymentMethod"
    ),
    payout_date_from: Optional[datetime] = Query(None, alias="payoutDateFrom"),
    payout_date_to: Optional[datetime] = Query(None, alias="payoutDateTo"),
    _: dict = Depends(require_role(["admin"])),
):
    _participant_or_404(participant_id)
    rows = fetch_payout_rows(
        supabase,
        user_id=participant_id,
        recipient_type="participant",
        q=q,
        status=payout_status,
        payout_type=payout_type,
        payment_method=payment_method,
        payout_date_from=payout_date_from,
        payout_date_to=payout_date_to,
    )
    return [PayoutResponse.model_validate(r) for r in rows]


@router.get(
    "/partners/{partner_id}/payouts",
    response_model=List[PayoutResponse],
    summary="List payouts for a partner (admin detail view)",
    description="Returns all payouts for `recipientType=partner` and `userId=partnerId` (e.g. MLM levels).",
)
def admin_list_payouts_for_partner(
    partner_id: str,
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
        description="MLM downline level",
        alias="levelDepth",
    ),
    _: dict = Depends(require_role(["admin"])),
):
    _partner_or_404(partner_id)
    rows = fetch_payout_rows(
        supabase,
        user_id=partner_id,
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
