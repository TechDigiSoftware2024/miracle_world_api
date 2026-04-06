from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.property import PropertyCreate, PropertyResponse, PropertyUpdate
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/properties", tags=["Admin", "Properties"])

_TABLE = "properties"


def _row_or_404(property_id: int) -> dict:
    result = supabase.table(_TABLE).select("*").eq("id", property_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property not found",
        )
    return result.data[0]


@router.get("", response_model=List[PropertyResponse])
def admin_list_properties(
    current_user: dict = Depends(require_role(["admin"])),
):
    try:
        result = (
            supabase.table(_TABLE)
            .select("*")
            .order("createdAt", desc=True)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [PropertyResponse.model_validate(row) for row in (result.data or [])]


@router.post("", response_model=PropertyResponse, status_code=status.HTTP_201_CREATED)
def admin_create_property(
    payload: PropertyCreate,
    current_user: dict = Depends(require_role(["admin"])),
):
    body = payload.model_dump(exclude_none=True)
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
            detail="Could not read property after insert.",
        )
    return PropertyResponse.model_validate(row)


@router.get("/{property_id}", response_model=PropertyResponse)
def admin_get_property(
    property_id: int,
    current_user: dict = Depends(require_role(["admin"])),
):
    return PropertyResponse.model_validate(_row_or_404(property_id))


@router.patch("/{property_id}", response_model=PropertyResponse)
def admin_patch_property(
    property_id: int,
    payload: PropertyUpdate,
    current_user: dict = Depends(require_role(["admin"])),
):
    _row_or_404(property_id)
    data = dump_update_or_400(payload)
    now = datetime.now(timezone.utc).isoformat()
    patch = {**data, "updatedAt": now}
    try:
        updated = (
            supabase.table(_TABLE)
            .update(patch)
            .eq("id", property_id)
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = (
                supabase.table(_TABLE).select("*").eq("id", property_id).execute()
            )
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read property after update.",
            )
        return PropertyResponse.model_validate(row)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.delete("/{property_id}")
def admin_delete_property(
    property_id: int,
    current_user: dict = Depends(require_role(["admin"])),
):
    _row_or_404(property_id)
    try:
        supabase.table(_TABLE).delete().eq("id", property_id).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return {"message": "Property deleted", "id": str(property_id), "propertyId": property_id}
