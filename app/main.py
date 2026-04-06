import logging
from typing import Optional

import httpx
from fastapi import FastAPI
from postgrest.exceptions import APIError

from app.core.config import SUPABASE_KEY, SUPABASE_URL
from app.db.database import supabase
from app.utils.db_column_names import camel_participant_pk_column, camel_partner_pk_column

from app.routers.request import router as request_router
from app.routers.contact import router as contact_router
from app.routers.app_settings_public import router as app_settings_public_router
from app.routers.unified_login import router as unified_login_router
from app.routers.otp_auth import router as otp_auth_router
from app.routers.admin import router as admin_router
from app.routers.participant import router as participant_router
from app.routers.partner import router as partner_router
from app.routers.fund_types_public import router as fund_types_public_router
from app.routers.fund_types_admin import router as fund_types_admin_router
from app.routers.properties_public import router as properties_public_router
from app.routers.properties_admin import router as properties_admin_router

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
1. **Contact (public)**: `POST /contact` with `name`, `email`, `phone` (10 digits), optional `message` — saves to Supabase `contact_queries`; optional SMTP notifies **CONTACT_NOTIFY_TO**.
2. **App settings**: Public `GET /settings` (company + default participant/partner IDs). Admin `GET /admin/settings` and `PATCH /admin/settings` to edit the same singleton row.
3. **New users** call `POST /request`, then `GET /track-request/{phone}` (each item includes **id**). Public `DELETE /request/{request_id}?phone=...` removes a request when **phone** matches that row.
4. **Optional**: `POST /check-admin-phone` with `{"phone":"..."}` returns `is_admin` so the UI can branch before mpin.
5. **Login (MPIN)**: `POST /login` — phone + **mpin**; tries **admin → participant → partner**. Use `role` in the response for the app shell.
6. **Login (OTP / MSG91)**: `POST /otp/send` → `POST /otp/login` with phone + **otp** (same JWT as MPIN login). Optional `POST /otp/retry`. Configure `MSG91_AUTH_KEY` and `MSG91_TEMPLATE_ID` on the server; Flutter should call **these** endpoints instead of embedding the MSG91 auth key in the app.
7. **Protected routes** need header: `Authorization: Bearer <access_token>` from login.
8. In **Swagger UI**, click **Authorize**, paste the token only (not the word Bearer), then call admin endpoints.
9. **Approve request**: `PUT /admin/request/{request_id}/approve` creates a row in **participants** or **partners** based on the request role and sets a new mpin on the request record.
10. **Admin directory**: Participants/partners/contact-queries/settings; user `DELETE`/`PATCH` by **`participantId`** / **`partnerId`**. **Fund types**: admin CRUD under `/admin/fund-types`; public `GET /fund-types` (active only). **Properties**: admin `GET|POST /admin/properties`, `GET|PATCH|DELETE /admin/properties/{id}`; **public (no token)** `GET /properties` (optional `?status=&type=&purpose=&city=`) and `GET /properties/{id}` for participant dashboards.
11. **Self profile**: `PATCH /participant/profile` and `PATCH /partner/profile` (participant or partner token); same rule — **phone** cannot be updated (omit it from JSON; sending unknown keys returns 422).
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

    result = supabase.table("admins").select("adminId").eq("phone", "9131718611").execute()
    if not result.data:
        supabase.table("admins").insert({
            "adminId": "MWA000001",
            "name": "Arjun",
            "phone": "9131718611",
            "mpin": "000000",
            "access_sections": "all",
        }).execute()

    pid = camel_participant_pk_column()
    result = supabase.table("participants").select(pid).eq("phone", "7030756931").execute()
    if not result.data:
        row = {
            pid: "MWP000001",
            "name": "Miracle World Participant",
            "phone": "7030756931",
            "email": "",
            "address": "",
            "introducer": "SYSTEM",
            "mpin": "000000",
            "status": "active",
            "totalInvestment": 0.0,
        }
        supabase.table("participants").insert(row).execute()

    prid = camel_partner_pk_column()
    result = supabase.table("partners").select(prid).eq("phone", "7030756931").execute()
    if not result.data:
        row = {
            prid: "MWCP000001",
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
        }
        supabase.table("partners").insert(row).execute()

    try:
        settings_row = (
            supabase.table("app_settings").select("id").eq("id", 1).limit(1).execute()
        )
        if not settings_row.data:
            supabase.table("app_settings").insert({
                "id": 1,
                "defaultPartnerId": "MWCP000001",
                "defaultParticipantId": "MWP000001",
                "companyName": "Miracle World Real Estate LLP",
                "companyEmail": "info@miracleworldllp.com",
                "companyPhone": "+91 6204599636",
                "companyAddress": "906-907, Gera Imperium Alpha, Pune",
            }).execute()
    except APIError as e:
        raw = e.args[0] if e.args else {}
        code = raw.get("code") if isinstance(raw, dict) else None
        missing_table = code == "PGRST205" or (
            isinstance(raw, dict)
            and "app_settings" in (raw.get("message") or "").lower()
        )
        if missing_table:
            logger.warning(
                "app_settings table not found; skipped seed for that table. "
                "Run repo file supabase_app_settings_table.sql in Supabase SQL Editor, then restart. "
                "GET /settings and /admin/settings will 404 until then."
            )
        else:
            raise


try:
    seed_defaults()
except (httpx.ConnectError, httpx.TimeoutException) as e:
    logger.warning(
        "Cannot reach Supabase (%s); app will start but DB calls will fail until URL/network/key are fixed.",
        e,
    )
except APIError as e:
    raw = e.args[0] if e.args else e
    logger.warning("Supabase rejected seed_defaults (check SUPABASE_KEY): %s", e)
    if isinstance(raw, dict) and raw.get("code") == "42703":
        logger.warning(
            "PostgREST reported an undefined column (42703). If you renamed tables manually, align "
            "with repo supabase_tables.sql or run supabase_rename_legacy_id_columns.sql in Supabase SQL Editor."
        )
    if isinstance(raw, dict) and raw.get("code") == "PGRST205":
        logger.warning(
            "PostgREST could not find a table (PGRST205). Create missing tables from repo SQL files "
            "(e.g. supabase_app_settings_table.sql, supabase_contact_queries_table.sql, supabase_fund_types_table.sql, supabase_properties_table.sql)."
        )
except Exception as e:
    logger.warning("seed_defaults failed: %s", e)

app.include_router(request_router)
app.include_router(contact_router)
app.include_router(app_settings_public_router)
app.include_router(fund_types_public_router)
app.include_router(properties_public_router)
app.include_router(unified_login_router)
app.include_router(otp_auth_router)
app.include_router(admin_router)
app.include_router(fund_types_admin_router, prefix="/admin")
app.include_router(properties_admin_router, prefix="/admin")
app.include_router(participant_router)
app.include_router(partner_router)


@app.get("/")
def home():
    return {"message": "Miracle World API is running"}
