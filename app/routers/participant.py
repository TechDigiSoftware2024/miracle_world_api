from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import bearer_scheme, require_role
from app.core.security import create_token, decode_token
from app.schemas.participant import ParticipantResponse, ParticipantUpdate
from app.schemas.auth import LoginRequest, TokenResponse
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/participant", tags=["Participant"])

# ─── PUBLIC: Login ───────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
def participant_login(payload: LoginRequest):
    result = (
        supabase.table("participants")
        .select("*")
        .eq("phone", payload.phone)
        .eq("mpin", payload.mpin)
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid phone or mpin",
        )

    p = result.data[0]
    uid = str(p.get("participantId") or p.get("investorId") or "")
    token = create_token({
        "sub": p["phone"],
        "role": "participant",
        "userId": uid,
        "name": p["name"],
    })

    return TokenResponse(
        access_token=token,
        role="participant",
        userId=uid,
        name=p["name"],
    )


# ─── PROTECTED: Logout ──────────────────────────────────────────


@router.post("/logout")
def participant_logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    current_user: dict = Depends(require_role(["participant", "admin"])),
):
    token = credentials.credentials
    payload = decode_token(token)
    jti = payload.get("jti")

    existing = supabase.table("token_blacklist").select("id").eq("jti", jti).execute()
    if not existing.data:
        supabase.table("token_blacklist").insert({"jti": jti}).execute()

    return {"message": "Logged out successfully"}


# ─── PROTECTED: Profile ─────────────────────────────────────────


@router.get("/profile", response_model=ParticipantResponse)
def get_participant_profile(
    current_user: dict = Depends(require_role(["participant", "admin"])),
):
    result = (
        supabase.table("participants")
        .select("*")
        .eq("phone", current_user["sub"])
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Participant not found",
        )
    return result.data[0]


# ─── PROTECTED: Update profile (phone cannot be changed) ────────


@router.patch("/profile", response_model=ParticipantResponse)
def patch_participant_profile(
    payload: ParticipantUpdate,
    current_user: dict = Depends(require_role(["participant"])),
):
    data = dump_update_or_400(payload)
    try:
        updated = (
            supabase.table("participants")
            .update(data)
            .eq("phone", current_user["sub"])
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = (
                supabase.table("participants")
                .select("*")
                .eq("phone", current_user["sub"])
                .execute()
            )
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Participant not found",
            )
        return row
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
