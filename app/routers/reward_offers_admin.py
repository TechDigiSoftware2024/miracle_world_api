import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.reward_program import (
    RewardOfferAdminCreate,
    RewardOfferResponse,
    RewardOfferUpdate,
)
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/reward-offers", tags=["Admin", "Reward offers"])

_TABLE = "reward_offers"
_PROGRAMS = "reward_programs"


def _program_exists(program_id: int) -> bool:
    r = supabase.table(_PROGRAMS).select("id").eq("id", program_id).limit(1).execute()
    return bool(r.data)


def _row_or_404(offer_id: str) -> dict:
    result = supabase.table(_TABLE).select("*").eq("id", offer_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reward offer not found",
        )
    return result.data[0]


@router.get("", response_model=List[RewardOfferResponse])
def admin_list_reward_offers(
    program_id: Optional[int] = Query(None, description="Filter by reward program id"),
    _: dict = Depends(require_role(["admin"])),
):
    try:
        q = supabase.table(_TABLE).select("*").order("createdAt", desc=True)
        if program_id is not None:
            q = q.eq("programId", program_id)
        result = q.execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [RewardOfferResponse.model_validate(r) for r in (result.data or [])]


@router.post("", response_model=RewardOfferResponse, status_code=status.HTTP_201_CREATED)
def admin_create_reward_offer(
    payload: RewardOfferAdminCreate,
    _: dict = Depends(require_role(["admin"])),
):
    if not _program_exists(payload.programId):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reward program not found",
        )
    oid = payload.id or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    body = {
        "id": oid,
        "programId": payload.programId,
        "title": payload.title,
        "description": payload.description,
        "imageUrl": payload.imageUrl,
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
        refetch = (
            supabase.table(_TABLE).select("*").eq("id", oid).execute()
        )
        row = refetch.data[0] if refetch.data else None
    if not row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read reward offer after insert.",
        )
    return RewardOfferResponse.model_validate(row)


@router.get("/{offer_id}", response_model=RewardOfferResponse)
def admin_get_reward_offer(
    offer_id: str,
    _: dict = Depends(require_role(["admin"])),
):
    return RewardOfferResponse.model_validate(_row_or_404(offer_id))


@router.patch("/{offer_id}", response_model=RewardOfferResponse)
def admin_patch_reward_offer(
    offer_id: str,
    payload: RewardOfferUpdate,
    _: dict = Depends(require_role(["admin"])),
):
    _row_or_404(offer_id)
    data = dump_update_or_400(payload)
    now = datetime.now(timezone.utc).isoformat()
    patch = {**data, "updatedAt": now}
    try:
        updated = (
            supabase.table(_TABLE)
            .update(patch)
            .eq("id", offer_id)
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = supabase.table(_TABLE).select("*").eq("id", offer_id).execute()
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read reward offer after update.",
            )
        return RewardOfferResponse.model_validate(row)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.delete("/{offer_id}")
def admin_delete_reward_offer(
    offer_id: str,
    _: dict = Depends(require_role(["admin"])),
):
    _row_or_404(offer_id)
    try:
        supabase.table(_TABLE).delete().eq("id", offer_id).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return {"message": "Reward offer deleted", "id": offer_id}
