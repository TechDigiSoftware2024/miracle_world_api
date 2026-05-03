from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.core.security import decode_token

bearer_scheme = HTTPBearer()

_ADMIN_SECTION_BY_PREFIX = {
    "request": "requests",
    "requests": "requests",
    "participants": "participants",
    "partners": "partners",
    "contact-queries": "contact_queries",
    "settings": "settings",
    "fund-types": "fund_types",
    "properties": "properties",
    "bank-details": "bank_details",
    "nominees": "nominees",
    "manual-kyc": "manual_kyc",
    "reward-programs": "rewards",
    "reward-offers": "rewards",
    "reward-achievements": "rewards",
    "investments": "investments",
    "payment-schedules": "investments",
    "pending-payments": "pending_payments",
    "closing-reports": "closing_reports",
    "schedule-visits": "schedule_visits",
    "payouts": "payouts",
    "payout-recipients": "payouts",
    "admin-users": "admins",
}

_ALWAYS_ALLOWED_ADMIN_PATHS = {
    "/admin/profile",
    "/admin/logout",
}


def _normalize_sections(raw: str) -> set[str]:
    sections = {s.strip().lower() for s in str(raw or "").split(",") if s.strip()}
    return sections or {"all"}


def _admin_section_from_path(path: str) -> str | None:
    p = str(path or "").strip().lower()
    if not p.startswith("/admin/"):
        return None
    if p in _ALWAYS_ALLOWED_ADMIN_PATHS:
        return None
    suffix = p[len("/admin/") :].strip()
    if not suffix:
        return None
    # Multi-segment routes (must be checked before first-path-prefix rules).
    if suffix.startswith("participants/special-funds"):
        return "special_funds"
    if suffix.startswith("partners/financials"):
        return "partner_portfolio"

    first = suffix.split("/", 1)[0].strip()
    if not first:
        return None
    return _ADMIN_SECTION_BY_PREFIX.get(first)


def _fetch_admin_access_row(admin_id: str) -> dict:
    aid = str(admin_id or "").strip()
    if not aid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing admin id",
        )
    try:
        result = (
            supabase.table("admins")
            .select("adminId,status,role,access_sections")
            .eq("adminId", aid)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin account not found",
            )
        return result.data[0]
    except HTTPException:
        raise
    except APIError:
        # Backward compatibility if role column is not migrated yet.
        fallback = (
            supabase.table("admins")
            .select("adminId,status,access_sections")
            .eq("adminId", aid)
            .limit(1)
            .execute()
        )
        if not fallback.data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin account not found",
            )
        row = fallback.data[0]
        row["role"] = "super_admin"
        return row


def _enforce_admin_section_access(current_user: dict, request: Request) -> dict:
    user_role = str(current_user.get("role") or "").strip().lower()
    if user_role != "admin":
        return current_user
    admin_id = str(current_user.get("adminId") or current_user.get("userId") or "").strip()
    row = _fetch_admin_access_row(admin_id)
    if str(row.get("status") or "active").strip().lower() != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin account is inactive",
        )
    admin_role = str(row.get("role") or "super_admin").strip().lower()
    access_sections = str(row.get("access_sections") or "all").strip().lower()
    current_user["adminRole"] = admin_role
    current_user["accessSections"] = access_sections
    if admin_role == "super_admin":
        return current_user
    required_section = _admin_section_from_path(request.url.path)
    if not required_section:
        return current_user
    allowed = _normalize_sections(access_sections)
    if "all" in allowed or required_section in allowed:
        return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Sub-admin access denied for section '{required_section}'",
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or malformed token",
        )

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    result = supabase.table("token_blacklist").select("id").eq("jti", jti).execute()
    if result.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked. Please login again.",
        )

    return payload


def require_role(allowed_roles: list):
    def role_checker(
        request: Request,
        current_user: dict = Depends(get_current_user),
    ):
        user_role = current_user.get("role")
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource",
            )
        return _enforce_admin_section_access(current_user, request)
    return role_checker
