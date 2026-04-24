from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.fund_type import FundTypeCreate, FundTypeResponse, FundTypeUpdate
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/fund-types", tags=["Admin", "Fund types"])

_TABLE = "fund_types"


def _row_or_404(fund_id: int) -> dict:
    result = supabase.table(_TABLE).select("*").eq("id", fund_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fund type not found",
        )
    return result.data[0]


@router.get("", response_model=List[FundTypeResponse])
def admin_list_fund_types(
    isSpecial: Optional[bool] = Query(
        default=None,
        description="If set, return only fund types with this isSpecial value (e.g. true for special funds).",
    ),
    current_user: dict = Depends(require_role(["admin"])),
):
    try:
        q = supabase.table(_TABLE).select("*")
        if isSpecial is not None:
            q = q.eq("isSpecial", isSpecial)
        result = q.order("createdAt", desc=True).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [FundTypeResponse.model_validate(row) for row in (result.data or [])]


@router.post("", response_model=FundTypeResponse, status_code=status.HTTP_201_CREATED)
def admin_create_fund_type(
    payload: FundTypeCreate,
    current_user: dict = Depends(require_role(["admin"])),
):
    body = payload.model_dump()
    try:
        inserted = supabase.table(_TABLE).insert(body).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    row = inserted.data[0] if inserted.data else None
    if not row:
        refetch = (
            supabase.table(_TABLE)
            .select("*")
            .order("createdAt", desc=True)
            .limit(1)
            .execute()
        )
        row = refetch.data[0] if refetch.data else None
    if not row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read fund type after insert.",
        )
    return FundTypeResponse.model_validate(row)


@router.get("/{fund_id}", response_model=FundTypeResponse)
def admin_get_fund_type(
    fund_id: int,
    current_user: dict = Depends(require_role(["admin"])),
):
    return FundTypeResponse.model_validate(_row_or_404(fund_id))


@router.patch("/{fund_id}", response_model=FundTypeResponse)
def admin_patch_fund_type(
    fund_id: int,
    payload: FundTypeUpdate,
    current_user: dict = Depends(require_role(["admin"])),
):
    _row_or_404(fund_id)
    data = dump_update_or_400(payload)
    now = datetime.now(timezone.utc).isoformat()
    patch = {**data, "updatedAt": now}
    try:
        updated = (
            supabase.table(_TABLE)
            .update(patch)
            .eq("id", fund_id)
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = (
                supabase.table(_TABLE).select("*").eq("id", fund_id).execute()
            )
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read fund type after update.",
            )
        return FundTypeResponse.model_validate(row)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.delete("/{fund_id}")
def admin_delete_fund_type(
    fund_id: int,
    current_user: dict = Depends(require_role(["admin"])),
):
    _row_or_404(fund_id)
    try:
        supabase.table(_TABLE).delete().eq("id", fund_id).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return {"message": "Fund type deleted", "fundId": fund_id}
