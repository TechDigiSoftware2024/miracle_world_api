from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.reward_program import (
    RewardProgramCreate,
    RewardProgramResponse,
    RewardProgramUpdate,
)
from app.utils.patch_payload import dump_update_or_400
from app.utils.reward_program_dates import compute_end_date
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/reward-programs", tags=["Admin", "Reward programs"])

_TABLE = "reward_programs"


def _parse_ts(v) -> datetime:
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Invalid timestamp in database row",
    )


def _row_or_404(program_id: int) -> dict:
    result = supabase.table(_TABLE).select("*").eq("id", program_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reward program not found",
        )
    return result.data[0]


def _serialize_program_body(data: dict) -> dict:
    out = {}
    for k, v in data.items():
        if v is None:
            out[k] = None
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


@router.get("", response_model=List[RewardProgramResponse])
def admin_list_reward_programs(
    _: dict = Depends(require_role(["admin"])),
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
    return [RewardProgramResponse.model_validate(r) for r in (result.data or [])]


@router.post("", response_model=RewardProgramResponse, status_code=status.HTTP_201_CREATED)
def admin_create_reward_program(
    payload: RewardProgramCreate,
    _: dict = Depends(require_role(["admin"])),
):
    end = compute_end_date(payload.startDate, payload.goalDays)
    body = _serialize_program_body({
        **payload.model_dump(),
        "endDate": end,
    })
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
            detail="Could not read reward program after insert.",
        )
    return RewardProgramResponse.model_validate(row)


@router.get("/{program_id}", response_model=RewardProgramResponse)
def admin_get_reward_program(
    program_id: int,
    _: dict = Depends(require_role(["admin"])),
):
    return RewardProgramResponse.model_validate(_row_or_404(program_id))


@router.patch("/{program_id}", response_model=RewardProgramResponse)
def admin_patch_reward_program(
    program_id: int,
    payload: RewardProgramUpdate,
    _: dict = Depends(require_role(["admin"])),
):
    existing = _row_or_404(program_id)
    data = dump_update_or_400(payload)
    if "startDate" in data or "goalDays" in data:
        sd = data.get("startDate")
        if sd is None:
            sd = _parse_ts(existing.get("startDate"))
        elif isinstance(sd, str):
            sd = datetime.fromisoformat(sd.replace("Z", "+00:00"))
        gd = data.get("goalDays")
        if gd is None:
            gd = int(existing.get("goalDays") or 0)
        patch_data = {**data, "endDate": compute_end_date(sd, int(gd))}
    else:
        patch_data = data

    now = datetime.now(timezone.utc).isoformat()
    patch = _serialize_program_body({**patch_data, "updatedAt": now})
    try:
        updated = (
            supabase.table(_TABLE)
            .update(patch)
            .eq("id", program_id)
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = supabase.table(_TABLE).select("*").eq("id", program_id).execute()
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read reward program after update.",
            )
        return RewardProgramResponse.model_validate(row)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.delete("/{program_id}")
def admin_delete_reward_program(
    program_id: int,
    _: dict = Depends(require_role(["admin"])),
):
    _row_or_404(program_id)
    try:
        supabase.table(_TABLE).delete().eq("id", program_id).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return {"message": "Reward program deleted", "id": program_id}
