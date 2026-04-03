from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app.db.database import supabase
from app.dependencies.auth import bearer_scheme, require_role
from app.core.security import create_token, decode_token
from app.schemas.partner import PartnerResponse
from app.schemas.auth import LoginRequest, TokenResponse

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
    token = create_token({
        "sub": partner["phone"],
        "role": "partner",
        "userId": partner["agentId"],
        "name": partner["name"],
    })

    return TokenResponse(
        access_token=token,
        role="partner",
        userId=partner["agentId"],
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
