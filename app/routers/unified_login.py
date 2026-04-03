from fastapi import APIRouter, HTTPException, status

from app.db.database import supabase
from app.core.security import create_token
from app.schemas.auth import LoginRequest, TokenResponse

router = APIRouter(tags=["Auth"])


@router.post("/login", response_model=TokenResponse)
def unified_login(payload: LoginRequest):
    """Single login for mobile: tries admin, then participant, then partner (same phone + mpin)."""
    admin = (
        supabase.table("admins")
        .select("*")
        .eq("phone", payload.phone)
        .eq("mpin", payload.mpin)
        .execute()
    )
    if admin.data:
        a = admin.data[0]
        token = create_token({
            "sub": a["phone"],
            "role": "admin",
            "userId": a["adminId"],
            "name": a["name"],
        })
        return TokenResponse(
            access_token=token,
            role="admin",
            userId=a["adminId"],
            name=a["name"],
        )

    participant = (
        supabase.table("participants")
        .select("*")
        .eq("phone", payload.phone)
        .eq("mpin", payload.mpin)
        .execute()
    )
    if participant.data:
        p = participant.data[0]
        token = create_token({
            "sub": p["phone"],
            "role": "participant",
            "userId": p["investorId"],
            "name": p["name"],
        })
        return TokenResponse(
            access_token=token,
            role="participant",
            userId=p["investorId"],
            name=p["name"],
        )

    partner = (
        supabase.table("partners")
        .select("*")
        .eq("phone", payload.phone)
        .eq("mpin", payload.mpin)
        .execute()
    )
    if partner.data:
        pr = partner.data[0]
        token = create_token({
            "sub": pr["phone"],
            "role": "partner",
            "userId": pr["agentId"],
            "name": pr["name"],
        })
        return TokenResponse(
            access_token=token,
            role="partner",
            userId=pr["agentId"],
            name=pr["name"],
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid phone or mpin",
    )
