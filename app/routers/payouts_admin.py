from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.payout import PayoutAdminCreate, PayoutAdminUpdate, PayoutResponse
from app.utils.db_column_names import camel_participant_pk_column, camel_partner_pk_column
from app.utils.payout_id import new_payout_id
from app.utils.payout_query import fetch_payout_rows
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error
from app.services.participant_portfolio_recalc import recalculate_participant_portfolio

router = APIRouter(prefix="/payouts", tags=["Admin", "Payouts"])

_TABLE = "payouts"
_INV = "investments"


def _row_or_404(payout_id: str) -> dict:
    result = supabase.table(_TABLE).select("*").eq("payoutId", payout_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payout not found",
        )
    return result.data[0]


def _assert_recipient_exists(user_id: str, recipient_type: str) -> None:
    p_pk = camel_participant_pk_column()
    a_pk = camel_partner_pk_column()
    uid = str(user_id).strip()
    if recipient_type == "participant":
        r = supabase.table("participants").select(p_pk).eq(p_pk, uid).limit(1).execute()
    else:
        r = supabase.table("partners").select(a_pk).eq(a_pk, uid).limit(1).execute()
    if not r.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No {recipient_type} found for userId {uid}",
        )


def _recalc_if_participant_payout(user_id: str, recipient_type: str) -> None:
    if str(recipient_type or "").strip() == "participant":
        recalculate_participant_portfolio(str(user_id or "").strip())


def _validate_investment_for_user(
    investment_id: str,
    user_id: str,
    recipient_type: str,
) -> None:
    r = supabase.table(_INV).select("*").eq("investmentId", investment_id).limit(1).execute()
    if not r.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Investment not found for investmentId",
        )
    inv = r.data[0]
    if recipient_type == "participant":
        if str(inv.get("participantId", "")).strip() != str(user_id).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Investment does not belong to this participant",
            )
    else:
        if str(inv.get("agentId", "")).strip() != str(user_id).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Investment is not linked to this partner (agentId)",
            )


@router.post("", response_model=PayoutResponse, status_code=status.HTTP_201_CREATED)
def admin_create_payout(
    payload: PayoutAdminCreate,
    current_user: dict = Depends(require_role(["admin"])),
):
    _assert_recipient_exists(payload.userId, payload.recipientType)
    if payload.investmentId and str(payload.investmentId).strip():
        _validate_investment_for_user(
            str(payload.investmentId).strip(),
            payload.userId,
            payload.recipientType,
        )

    pid = new_payout_id()
    now = datetime.now(timezone.utc).isoformat()
    admin_id = str(current_user.get("userId", "")).strip()
    by_admin = payload.createdBy == "admin" or str(payload.createdBy) == "admin"
    body = {
        "payoutId": pid,
        "userId": str(payload.userId).strip(),
        "recipientType": payload.recipientType,
        "amount": float(payload.amount),
        "status": payload.status,
        "paymentMethod": payload.paymentMethod,
        "transactionId": payload.transactionId,
        "investmentId": (str(payload.investmentId).strip() if payload.investmentId else None),
        "payoutDate": (
            payload.payoutDate.isoformat()
            if isinstance(payload.payoutDate, datetime)
            else payload.payoutDate
        ),
        "remarks": payload.remarks or "",
        "payoutType": payload.payoutType,
        "createdBy": payload.createdBy,
        "createdByAdminId": (admin_id if by_admin else None),
        "levelDepth": payload.levelDepth,
        "updatedAt": None,
    }
    try:
        inserted = supabase.table(_TABLE).insert(body).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    row = inserted.data[0] if inserted.data else None
    if not row:
        refetch = supabase.table(_TABLE).select("*").eq("payoutId", pid).execute()
        row = refetch.data[0] if refetch.data else None
    if not row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read payout after insert.",
        )
    _recalc_if_participant_payout(payload.userId, payload.recipientType)
    return PayoutResponse.model_validate(row)


@router.get("", response_model=List[PayoutResponse])
def admin_list_payouts(
    q: Optional[str] = Query(None, description="Search payout id, user id, investment, txn id, remarks"),
    payout_status: Optional[str] = Query(None, description="Filter by status", alias="payoutStatus"),
    payout_type: Optional[str] = Query(None, description="Filter by payoutType", alias="payoutType"),
    payment_method: Optional[str] = Query(
        None, description="Filter by paymentMethod (BANK, IMPS/NEFT, CASH)", alias="paymentMethod"
    ),
    userId: Optional[str] = Query(None, description="Filter by recipient user id"),
    recipientType: Optional[str] = Query(None, description="participant | partner"),
    payout_date_from: Optional[datetime] = Query(None, alias="payoutDateFrom"),
    payout_date_to: Optional[datetime] = Query(None, alias="payoutDateTo"),
    level_depth: Optional[int] = Query(
        None,
        ge=1,
        le=100,
        description="MLM downline level (partner payouts)",
        alias="levelDepth",
    ),
    _: dict = Depends(require_role(["admin"])),
):
    rows = fetch_payout_rows(
        supabase,
        user_id=userId,
        recipient_type=recipientType,
        q=q,
        status=payout_status,
        payout_type=payout_type,
        payment_method=payment_method,
        payout_date_from=payout_date_from,
        payout_date_to=payout_date_to,
        level_depth=level_depth,
    )
    return [PayoutResponse.model_validate(r) for r in rows]


@router.get("/{payout_id}", response_model=PayoutResponse)
def admin_get_payout(
    payout_id: str,
    _: dict = Depends(require_role(["admin"])),
):
    return PayoutResponse.model_validate(_row_or_404(payout_id))


@router.patch("/{payout_id}", response_model=PayoutResponse)
def admin_update_payout(
    payout_id: str,
    payload: PayoutAdminUpdate,
    _: dict = Depends(require_role(["admin"])),
):
    existing = _row_or_404(payout_id)
    data = dump_update_or_400(payload)
    target_uid = str(data["userId"]).strip() if "userId" in data else str(existing.get("userId", "")).strip()
    target_rt = str(data["recipientType"]).strip() if "recipientType" in data else str(
        existing.get("recipientType", "participant")
    ).strip()
    if "userId" in data or "recipientType" in data:
        _assert_recipient_exists(target_uid, target_rt)

    inv_effective = data.get("investmentId") if "investmentId" in data else existing.get("investmentId")
    if inv_effective is not None and str(inv_effective).strip():
        _validate_investment_for_user(
            str(inv_effective).strip(),
            target_uid,
            target_rt,
        )

    if target_rt == "participant":
        data["levelDepth"] = None

    now = datetime.now(timezone.utc).isoformat()
    if "payoutDate" in data and data["payoutDate"] is not None:
        d = data["payoutDate"]
        data["payoutDate"] = d.isoformat() if isinstance(d, datetime) else d
    for k in list(data):
        if data[k] is None and k in ("transactionId", "investmentId"):
            data[k] = None
    patch = {**data, "updatedAt": now}

    try:
        updated = supabase.table(_TABLE).update(patch).eq("payoutId", payout_id).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    row = updated.data[0] if updated.data else None
    if not row:
        refetch = supabase.table(_TABLE).select("*").eq("payoutId", payout_id).execute()
        row = refetch.data[0] if refetch.data else None
    if not row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read payout after update.",
        )
    new_uid = str(row.get("userId", "")).strip()
    new_rt = str(row.get("recipientType", "")).strip()
    old_uid = str(existing.get("userId", "")).strip()
    old_rt = str(existing.get("recipientType", "")).strip()
    _recalc_if_participant_payout(old_uid, old_rt)
    if new_uid != old_uid or new_rt != old_rt:
        _recalc_if_participant_payout(new_uid, new_rt)
    return PayoutResponse.model_validate(row)


@router.delete("/{payout_id}")
def admin_delete_payout(
    payout_id: str,
    _: dict = Depends(require_role(["admin"])),
):
    existing = _row_or_404(payout_id)
    old_uid = str(existing.get("userId", "")).strip()
    old_rt = str(existing.get("recipientType", "")).strip()
    try:
        supabase.table(_TABLE).delete().eq("payoutId", payout_id).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    _recalc_if_participant_payout(old_uid, old_rt)
    return {"message": "Payout deleted", "payoutId": payout_id}
