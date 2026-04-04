from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import bearer_scheme, require_role
from app.core.security import create_token, decode_token
from app.schemas.partner import PartnerResponse, PartnerUpdate
from app.schemas.auth import LoginRequest, TokenResponse
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/partner", tags=["Partner"])

# ─── PUBLIC: Login ───────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
def partner_login(payload: LoginRequest):
    result = (
        supabase.table("partners")
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

    partner = result.data[0]
    uid = str(partner.get("partnerId") or partner.get("agentId") or "")
    token = create_token({
        "sub": partner["phone"],
        "role": "partner",
        "userId": uid,
        "name": partner["name"],
    })

    return TokenResponse(
        access_token=token,
        role="partner",
        userId=uid,
        name=partner["name"],
    )


# ─── PROTECTED: Logout ──────────────────────────────────────────


@router.post("/logout")
def partner_logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    current_user: dict = Depends(require_role(["partner", "admin"])),
):
    token = credentials.credentials
    payload = decode_token(token)
    jti = payload.get("jti")

    existing = supabase.table("token_blacklist").select("id").eq("jti", jti).execute()
    if not existing.data:
        supabase.table("token_blacklist").insert({"jti": jti}).execute()

    return {"message": "Logged out successfully"}


# ─── PROTECTED: Profile ─────────────────────────────────────────


@router.get("/profile", response_model=PartnerResponse)
def get_partner_profile(
    current_user: dict = Depends(require_role(["partner", "admin"])),
):
    result = (
        supabase.table("partners")
        .select("*")
        .eq("phone", current_user["sub"])
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partner not found",
        )
    return result.data[0]


# ─── PROTECTED: Update profile (phone cannot be changed) ────────


@router.patch("/profile", response_model=PartnerResponse)
def patch_partner_profile(
    payload: PartnerUpdate,
    current_user: dict = Depends(require_role(["partner"])),
):
    data = dump_update_or_400(payload)
    try:
        updated = (
            supabase.table("partners")
            .update(data)
            .eq("phone", current_user["sub"])
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = (
                supabase.table("partners")
                .select("*")
                .eq("phone", current_user["sub"])
                .execute()
            )
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Partner not found",
            )
        return row
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
