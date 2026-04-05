from typing import List

from fastapi import APIRouter, HTTPException, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.schemas.fund_type import FundTypeResponse
from app.utils.supabase_errors import format_api_error

router = APIRouter(
    prefix="/fund-types",
    tags=["Public"],
)

_TABLE = "fund_types"


@router.get(
    "",
    response_model=List[FundTypeResponse],
    summary="List fund types (public, no auth)",
)
def list_active_fund_types():
    """
    **No `Authorization` header required** — safe to call from participant/partner/user dashboards
    or Flutter before login. Returns only **`status` = `active`**, newest first.
    """
    try:
        result = (
            supabase.table(_TABLE)
            .select("*")
            .eq("status", "active")
            .order("createdAt", desc=True)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [FundTypeResponse.model_validate(row) for row in (result.data or [])]


@router.get(
    "/{fund_id}",
    response_model=FundTypeResponse,
    summary="Get one fund type (public, no auth)",
)
def get_active_fund_type(fund_id: int):
    """
    **No auth.** Returns the fund only if it exists and **`status` is `active`**
    (same rule as the list endpoint — inactive funds are hidden from users).
    """
    try:
        result = (
            supabase.table(_TABLE)
            .select("*")
            .eq("id", fund_id)
            .eq("status", "active")
            .limit(1)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fund type not found or not available",
        )
    return FundTypeResponse.model_validate(result.data[0])
