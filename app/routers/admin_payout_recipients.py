from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.payout_recipient_lookup import PayoutRecipientParticipantItem, PayoutRecipientPartnerItem
from app.utils.db_column_names import camel_participant_pk_column, camel_partner_pk_column
from app.utils.phone_normalize import is_plausible_in_mobile, normalize_phone_digits
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/payout-recipients", tags=["Admin", "Payouts"])

_DEFAULT_LIMIT = 30
_MAX_LIMIT = 100


def _at_least_one(*values: Optional[str]) -> bool:
    return any((v or "").strip() for v in values)


def _apply_lookups(
    *,
    table: str,
    id_column: str,
    order_column: str,
    id_val: Optional[str],
    name_val: Optional[str],
    phone_val: Optional[str],
    limit: int,
):
    if not _at_least_one(id_val, name_val, phone_val):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one of: id, name, or phone",
        )

    q = supabase.table(table).select(f"{id_column},name,phone,status")
    p_id = (id_val or "").strip()
    n = (name_val or "").strip()
    p_phone = (phone_val or "").strip()

    if p_id:
        q = q.eq(id_column, p_id)
    if p_phone:
        if not is_plausible_in_mobile(p_phone):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="phone must be a plausible 10-digit mobile number",
            )
        q = q.eq("phone", normalize_phone_digits(p_phone))
    if n:
        safe = "".join(c for c in n if c not in "%_\\")
        if not safe.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="name must contain at least one valid character",
            )
        q = q.ilike("name", f"%{safe.strip()}%")

    try:
        result = q.order(order_column).limit(min(limit, _MAX_LIMIT)).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return list(result.data or [])


@router.get(
    "/participants",
    response_model=List[PayoutRecipientParticipantItem],
    summary="Search participants (payout / recipient picker)",
    description=(
        "Filter by **id** (exact `participantId`), **phone** (10-digit, exact), and/or **name** (partial, "
        "case-insensitive). At least one filter is required. All provided filters are combined with AND."
    ),
)
def admin_lookup_participants_for_payout(
    recipient_id: Optional[str] = Query(
        None,
        max_length=64,
        description="Exact participantId",
        alias="id",
    ),
    name: Optional[str] = Query(None, max_length=200, description="Partial match on name"),
    phone: Optional[str] = Query(
        None,
        max_length=20,
        description="Exact match on phone (10-digit India style after normalization)",
    ),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    _: dict = Depends(require_role(["admin"])),
):
    pid = camel_participant_pk_column()
    rows = _apply_lookups(
        table="participants",
        id_column=pid,
        order_column=pid,
        id_val=recipient_id,
        name_val=name,
        phone_val=phone,
        limit=limit,
    )
    return [PayoutRecipientParticipantItem.model_validate(r) for r in rows]


@router.get(
    "/partners",
    response_model=List[PayoutRecipientPartnerItem],
    summary="Search partners (payout / recipient picker)",
    description=(
        "Filter by **id** (exact `partnerId`), **phone** (10-digit, exact), and/or **name** (partial, "
        "case-insensitive). At least one filter is required. All provided filters are combined with AND."
    ),
)
def admin_lookup_partners_for_payout(
    recipient_id: Optional[str] = Query(
        None,
        max_length=64,
        description="Exact partnerId (or agentId in legacy DBs)",
        alias="id",
    ),
    name: Optional[str] = Query(None, max_length=200, description="Partial match on name"),
    phone: Optional[str] = Query(
        None,
        max_length=20,
        description="Exact match on phone (10-digit India style after normalization)",
    ),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    _: dict = Depends(require_role(["admin"])),
):
    prid = camel_partner_pk_column()
    rows = _apply_lookups(
        table="partners",
        id_column=prid,
        order_column=prid,
        id_val=recipient_id,
        name_val=name,
        phone_val=phone,
        limit=limit,
    )
    return [PayoutRecipientPartnerItem.model_validate(r) for r in rows]
