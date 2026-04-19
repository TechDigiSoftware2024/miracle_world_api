from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from postgrest.exceptions import APIError

from app.core.security import create_token, decode_token
from app.db.database import supabase
from app.dependencies.auth import bearer_scheme, require_role
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.phone_auth import issue_token_for_phone
from app.utils.phone_normalize import normalize_phone_digits
from app.utils.supabase_errors import format_api_error

router = APIRouter(tags=["Auth"])


@router.post("/login", response_model=TokenResponse)
def unified_login(payload: LoginRequest):
    """Single login for mobile: tries admin, then participant, then partner (phone + mpin)."""
    token = issue_token_for_phone(payload.phone, mpin=payload.mpin)
    if token:
        return token
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid phone or mpin",
    )


@router.post("/swap-role", response_model=TokenResponse)
def swap_role(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    current_user: dict = Depends(require_role(["participant", "partner"])),
):
    """
    Switch between participant and partner for the same phone when both accounts exist.
    Returns a new JWT for the **other** role (`role`, `userId`, `name`). The current token is revoked.
    """
    role = current_user.get("role")
    if role not in ("participant", "partner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Role swap is only for participant and partner accounts",
        )

    phone = normalize_phone_digits(str(current_user.get("sub", "")))
    if not phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token is missing a valid phone (sub)",
        )

    try:
        p_res = (
            supabase.table("participants")
            .select("*")
            .eq("phone", phone)
            .limit(1)
            .execute()
        )
        pr_res = (
            supabase.table("partners")
            .select("*")
            .eq("phone", phone)
            .limit(1)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e

    p_row = p_res.data[0] if p_res.data else None
    pr_row = pr_res.data[0] if pr_res.data else None

    if not p_row or not pr_row:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Both a participant and a partner account must exist for this phone to swap roles",
        )

    if role == "participant":
        target = pr_row
        new_role = "partner"
        uid = str(target.get("partnerId") or target.get("agentId") or "")
    else:
        target = p_row
        new_role = "participant"
        uid = str(target.get("participantId") or target.get("investorId") or "")

    if not uid:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not resolve user id for the target role",
        )

    token_str = credentials.credentials
    payload = decode_token(token_str)
    jti = payload.get("jti")
    if jti:
        existing = supabase.table("token_blacklist").select("id").eq("jti", jti).execute()
        if not existing.data:
            supabase.table("token_blacklist").insert({"jti": jti}).execute()

    access_token = create_token({
        "sub": target["phone"],
        "role": new_role,
        "userId": uid,
        "name": target["name"],
    })

    return TokenResponse(
        access_token=access_token,
        role=new_role,
        userId=uid,
        name=target["name"],
    )
