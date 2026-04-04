"""Resolve admin / participant / partner by phone (+ optional mpin) and build JWT payload."""

from typing import Optional

from app.core.security import create_token
from app.db.database import supabase
from app.schemas.auth import TokenResponse
from app.utils.phone_normalize import normalize_phone_digits


def issue_token_for_phone(phone: str, mpin: Optional[str] = None) -> Optional[TokenResponse]:
    """
    If mpin is set, require matching mpin (MPIN login).
    If mpin is None, match phone only (after OTP verification).
    Order: admin → participant → partner (same as unified /login).
    """
    normalized = normalize_phone_digits(phone)
    if not normalized:
        return None

    def q_admin():
        q = supabase.table("admins").select("*").eq("phone", normalized)
        if mpin is not None:
            q = q.eq("mpin", mpin)
        return q.execute()

    admin = q_admin()
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

    def q_participant():
        q = supabase.table("participants").select("*").eq("phone", normalized)
        if mpin is not None:
            q = q.eq("mpin", mpin)
        return q.execute()

    participant = q_participant()
    if participant.data:
        p = participant.data[0]
        puid = str(p.get("participantId") or p.get("investorId") or "")
        token = create_token({
            "sub": p["phone"],
            "role": "participant",
            "userId": puid,
            "name": p["name"],
        })
        return TokenResponse(
            access_token=token,
            role="participant",
            userId=puid,
            name=p["name"],
        )

    def q_partner():
        q = supabase.table("partners").select("*").eq("phone", normalized)
        if mpin is not None:
            q = q.eq("mpin", mpin)
        return q.execute()

    partner = q_partner()
    if partner.data:
        pr = partner.data[0]
        pruid = str(pr.get("partnerId") or pr.get("agentId") or "")
        token = create_token({
            "sub": pr["phone"],
            "role": "partner",
            "userId": pruid,
            "name": pr["name"],
        })
        return TokenResponse(
            access_token=token,
            role="partner",
            userId=pruid,
            name=pr["name"],
        )

    return None
