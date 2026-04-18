from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.nominee import NomineeCreate, NomineeResponse, NomineeUserUpdate
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/nominees", tags=["Nominees", "User"])

_TABLE = "nominees"


def _assert_self_or_admin(user_id: str, current_user: dict) -> None:
    role = current_user.get("role")
    if role == "admin":
        return
    if str(current_user.get("userId", "")).strip() != str(user_id).strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can access nominees only for your own userId",
        )


def _row_or_404(nominee_id: int) -> dict:
    result = supabase.table(_TABLE).select("*").eq("id", nominee_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nominee not found",
        )
    return result.data[0]


def _serialize_row_for_db(data: dict) -> dict:
    out = {}
    for k, v in data.items():
        if v is None:
            out[k] = None
        elif isinstance(v, date) and not isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


@router.get("/user/{user_id}", response_model=List[NomineeResponse])
def list_nominees_for_user(
    user_id: str,
    current_user: dict = Depends(require_role(["participant", "partner", "admin"])),
):
    _assert_self_or_admin(user_id, current_user)
    try:
        result = (
            supabase.table(_TABLE)
            .select("*")
            .eq("userId", user_id)
            .order("createdAt", desc=True)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [NomineeResponse.model_validate(r) for r in (result.data or [])]


@router.post("", response_model=NomineeResponse, status_code=status.HTTP_201_CREATED)
def create_nominee(
    payload: NomineeCreate,
    current_user: dict = Depends(require_role(["participant", "partner"])),
):
    uid = str(current_user.get("userId", "")).strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token is missing userId",
        )
    body = _serialize_row_for_db(
        {
            **payload.model_dump(mode="json"),
            "userId": uid,
            "status": "Pending",
            "rejectionReason": None,
            "verifiedBy": None,
            "verifiedAt": None,
            "updatedAt": None,
        }
    )
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
            .eq("userId", uid)
            .order("createdAt", desc=True)
            .limit(1)
            .execute()
        )
        row = refetch.data[0] if refetch.data else None
    if not row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read nominee after insert.",
        )
    return NomineeResponse.model_validate(row)


@router.put("/{nominee_id}", response_model=NomineeResponse)
def update_nominee(
    nominee_id: int,
    payload: NomineeUserUpdate,
    current_user: dict = Depends(require_role(["participant", "partner"])),
):
    row = _row_or_404(nominee_id)
    uid = str(current_user.get("userId", "")).strip()
    if str(row.get("userId", "")).strip() != uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can update only your own nominees",
        )
    if row.get("status") == "Verified":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verified nominees cannot be edited",
        )
    data = dump_update_or_400(payload)
    now = datetime.now(timezone.utc).isoformat()
    patch = _serialize_row_for_db({**data, "updatedAt": now})
    if row.get("status") == "Rejected":
        patch["status"] = "Pending"
        patch["rejectionReason"] = None
        patch["verifiedBy"] = None
        patch["verifiedAt"] = None
    try:
        updated = (
            supabase.table(_TABLE)
            .update(patch)
            .eq("id", nominee_id)
            .execute()
        )
        out = updated.data[0] if updated.data else None
        if not out:
            refetch = (
                supabase.table(_TABLE).select("*").eq("id", nominee_id).execute()
            )
            out = refetch.data[0] if refetch.data else None
        if not out:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read nominee after update.",
            )
        return NomineeResponse.model_validate(out)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
