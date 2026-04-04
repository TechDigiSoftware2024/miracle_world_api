from fastapi import APIRouter, HTTPException, status

from app.schemas.auth import LoginRequest, TokenResponse
from app.services.phone_auth import issue_token_for_phone

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
