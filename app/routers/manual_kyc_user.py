from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.manual_kyc import ManualKycCreate, ManualKycResponse, ManualKycUserUpdate
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/manual-kyc", tags=["Manual KYC", "User"])

_TABLE = "manual_kyc"


def _assert_self_or_admin(user_id: str, current_user: dict) -> None:
    role = current_user.get("role")
    if role == "admin":
        return
    if str(current_user.get("userId", "")).strip() != str(user_id).strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can access manual KYC only for your own userId",
        )


def _row_or_404(manual_kyc_id: int) -> dict:
    result = supabase.table(_TABLE).select("*").eq("id", manual_kyc_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manual KYC not found",
        )
    return result.data[0]


def _validate_merged_kyc(row: dict) -> None:
    t = row.get("kycType")
    if t == "PAN":
        if not str(row.get("panNumber", "")).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="panNumber is required when kycType is PAN",
            )
        if not str(row.get("panDocumentUrl", "")).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="panDocumentUrl is required when kycType is PAN",
            )
    elif t == "AADHAAR":
        if not str(row.get("aadhaarNumber", "")).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="aadhaarNumber is required when kycType is AADHAAR",
            )
        if not str(row.get("aadhaarDocumentUrl", "")).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="aadhaarDocumentUrl is required when kycType is AADHAAR",
            )
    elif t == "Both":
        if not str(row.get("panNumber", "")).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="panNumber is required when kycType is Both",
            )
        if not str(row.get("panDocumentUrl", "")).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="panDocumentUrl is required when kycType is Both",
            )
        if not str(row.get("aadhaarNumber", "")).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="aadhaarNumber is required when kycType is Both",
            )
        if not str(row.get("aadhaarDocumentUrl", "")).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="aadhaarDocumentUrl is required when kycType is Both",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid kycType",
        )


@router.get("/user/{user_id}", response_model=ManualKycResponse)
def get_manual_kyc_for_user(
    user_id: str,
    current_user: dict = Depends(require_role(["participant", "partner", "admin"])),
):
    _assert_self_or_admin(user_id, current_user)
    try:
        result = (
            supabase.table(_TABLE).select("*").eq("userId", user_id).limit(1).execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manual KYC not found for this user",
        )
    return ManualKycResponse.model_validate(result.data[0])


@router.post("", response_model=ManualKycResponse, status_code=status.HTTP_201_CREATED)
def create_manual_kyc(
    payload: ManualKycCreate,
    current_user: dict = Depends(require_role(["participant", "partner"])),
):
    uid = str(current_user.get("userId", "")).strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token is missing userId",
        )
    existing = (
        supabase.table(_TABLE).select("id").eq("userId", uid).limit(1).execute()
    )
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Manual KYC already exists for this user; use PUT to update",
        )
    body = {
        **payload.model_dump(),
        "userId": uid,
        "status": "Pending",
        "rejectionReason": None,
        "verifiedBy": None,
        "verifiedAt": None,
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
        refetch = supabase.table(_TABLE).select("*").eq("userId", uid).execute()
        row = refetch.data[0] if refetch.data else None
    if not row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read manual KYC after insert.",
        )
    return ManualKycResponse.model_validate(row)


@router.put("/{manual_kyc_id}", response_model=ManualKycResponse)
def update_manual_kyc(
    manual_kyc_id: int,
    payload: ManualKycUserUpdate,
    current_user: dict = Depends(require_role(["participant", "partner"])),
):
    row = _row_or_404(manual_kyc_id)
    uid = str(current_user.get("userId", "")).strip()
    if str(row.get("userId", "")).strip() != uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can update only your own manual KYC",
        )
    if row.get("status") == "Verified":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verified manual KYC cannot be edited",
        )
    data = dump_update_or_400(payload)
    merged = {**row, **data}
    _validate_merged_kyc(merged)

    now = datetime.now(timezone.utc).isoformat()
    patch = {**data, "updatedAt": now}
    if row.get("status") == "Rejected":
        patch["status"] = "Pending"
        patch["rejectionReason"] = None
        patch["verifiedBy"] = None
        patch["verifiedAt"] = None
    try:
        updated = (
            supabase.table(_TABLE)
            .update(patch)
            .eq("id", manual_kyc_id)
            .execute()
        )
        out = updated.data[0] if updated.data else None
        if not out:
            refetch = (
                supabase.table(_TABLE).select("*").eq("id", manual_kyc_id).execute()
            )
            out = refetch.data[0] if refetch.data else None
        if not out:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read manual KYC after update.",
            )
        return ManualKycResponse.model_validate(out)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
