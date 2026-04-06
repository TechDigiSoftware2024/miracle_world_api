from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.schemas.property import PropertyResponse
from app.utils.supabase_errors import format_api_error

router = APIRouter(
    prefix="/properties",
    tags=["Public"],
)

_TABLE = "properties"


@router.get(
    "",
    response_model=List[PropertyResponse],
    summary="List properties (public, no auth)",
)
def list_properties_public(
    status: Optional[str] = Query(
        default=None,
        description="Filter: available | sold | pending",
    ),
    property_type: Optional[str] = Query(
        default=None,
        alias="type",
        description="Filter: residential | commercial | land",
    ),
    purpose: Optional[str] = Query(
        default=None,
        description="Filter: rent | buy | sell",
    ),
    city: Optional[str] = Query(default=None, description="Filter by city (exact match)"),
):
    """
    **No authentication** — use on participant/user dashboards.
    Optional filters; omit them to return all properties (newest first).
    """
    try:
        q = supabase.table(_TABLE).select("*")
        if status:
            q = q.eq("status", status)
        if property_type:
            q = q.eq("type", property_type)
        if purpose:
            q = q.eq("purpose", purpose)
        if city and city.strip():
            q = q.eq("city", city.strip())
        result = q.order("createdAt", desc=True).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [PropertyResponse.model_validate(row) for row in (result.data or [])]


@router.get(
    "/{property_id}",
    response_model=PropertyResponse,
    summary="Get one property (public, no auth)",
)
def get_property_public(property_id: int):
    """**No auth.** Full property detail for dashboards / detail screens."""
    try:
        result = (
            supabase.table(_TABLE)
            .select("*")
            .eq("id", property_id)
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
            detail="Property not found",
        )
    return PropertyResponse.model_validate(result.data[0])
