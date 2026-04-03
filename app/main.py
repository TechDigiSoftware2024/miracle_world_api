import logging
from typing import Optional

import httpx
from fastapi import FastAPI
from postgrest.exceptions import APIError

from app.core.config import SUPABASE_KEY, SUPABASE_URL
from app.db.database import supabase

from app.routers.request import router as request_router
from app.routers.unified_login import router as unified_login_router
from app.routers.admin import router as admin_router
from app.routers.participant import router as participant_router
from app.routers.partner import router as partner_router

logger = logging.getLogger(__name__)


def _supabase_key_is_configured(key: Optional[str]) -> bool:
    k = (key or "").strip()
    if not k:
        return False
    if k.lower() in ("your-service-role-key-here", "your-anon-key-here"):
        return False
    # Project API keys are JWT-shaped (three segments)
    if k.count(".") != 2 or not k.startswith("eyJ"):
        return False
    return True


API_DESCRIPTION = """
## Flow
1. **New users** call `POST /request`, then `GET /track-request/{phone}`.
2. **Optional**: `POST /check-admin-phone` with `{"phone":"..."}` returns `is_admin` so the UI can branch before mpin.
3. **Login** (one screen): `POST /login` tries **admin → participant → partner** with the same phone + mpin. Use `role` in the response to open the correct app section. Role-specific logins (`/admin/login`, etc.) still work.
4. **Protected routes** need header: `Authorization: Bearer <access_token>` from login.
5. In **Swagger UI**, click **Authorize**, paste the token only (not the word Bearer), then call admin endpoints.
6. **Approve request**: `PUT /admin/request/{request_id}/approve` creates a row in **participants** or **partners** based on the request role and sets a new mpin on the request record.
"""

app = FastAPI(
    title="Miracle World API",
    version="0.1.0",
    description=API_DESCRIPTION,
    swagger_ui_parameters={"persistAuthorization": True},
)


def seed_defaults() -> None:
    if not SUPABASE_URL or "YOUR_PROJECT_REF" in SUPABASE_URL.upper():
        logger.warning(
            "SUPABASE_URL is missing or still a placeholder; skipping seed_defaults. "
            "Set a real URL in .env (Supabase Dashboard > Settings > API)."
        )
        return

    if not _supabase_key_is_configured(SUPABASE_KEY):
        logger.warning(
            "SUPABASE_KEY is missing, placeholder, or not a valid Supabase JWT. "
            "Use the service_role key: Supabase Dashboard > Settings > API > "
            "Project API keys > service_role (Reveal). Paste the full token into .env "
            "or Render Environment. Skipping seed_defaults."
        )
        return

    result = supabase.table("admins").select("id").eq("phone", "9131718611").execute()
    if not result.data:
        supabase.table("admins").insert({
            "adminId": "MWA000001",
            "name": "Arjun",
            "phone": "9131718611",
            "mpin": "000000",
            "access_sections": "all",
        }).execute()

    result = supabase.table("participants").select("id").eq("phone", "7030756931").execute()
    if not result.data:
        supabase.table("participants").insert({
            "investorId": "MWP000001",
            "name": "Miracle World Participant",
            "phone": "7030756931",
            "email": "",
            "address": "",
            "introducer": "SYSTEM",
            "mpin": "000000",
            "status": "active",
        }).execute()

    result = supabase.table("partners").select("id").eq("phone", "7030756931").execute()
    if not result.data:
        supabase.table("partners").insert({
            "agentId": "MWCP000001",
            "name": "Miracle World Partner",
            "phone": "7030756931",
            "email": "",
            "location": "",
            "introducer": "SYSTEM",
            "mpin": "000000",
            "status": "active",
            "commission": 0.0,
            "selfCommission": 0.0,
            "selfProfit": 0.0,
            "generatedProfitByTeam": 0.0,
            "totalDeals": 0,
            "totalTeamMembers": 0,
        }).execute()


try:
    seed_defaults()
except (httpx.ConnectError, httpx.TimeoutException) as e:
    logger.warning(
        "Cannot reach Supabase (%s); app will start but DB calls will fail until URL/network/key are fixed.",
        e,
    )
except APIError as e:
    logger.warning("Supabase rejected seed_defaults (check SUPABASE_KEY): %s", e)
except Exception as e:
    logger.warning("seed_defaults failed: %s", e)

app.include_router(request_router)
app.include_router(unified_login_router)
app.include_router(admin_router)
app.include_router(participant_router)
app.include_router(partner_router)


@app.get("/")
def home():
    return {"message": "Miracle World API is running"}
