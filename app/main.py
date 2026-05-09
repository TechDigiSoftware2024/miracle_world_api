import logging
from typing import Optional

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
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
from app.routers.participant_special_funds_admin import router as participant_special_funds_admin_router
from app.routers.participant import router as participant_router
from app.routers.partner import router as partner_router
from app.routers.fund_types_public import router as fund_types_public_router
from app.routers.fund_types_admin import router as fund_types_admin_router
from app.routers.properties_public import router as properties_public_router
from app.routers.properties_admin import router as properties_admin_router
from app.routers.bank_details_user import router as bank_details_user_router
from app.routers.bank_details_admin import router as bank_details_admin_router
from app.routers.nominee_user import router as nominee_user_router
from app.routers.nominee_admin import router as nominee_admin_router
from app.routers.manual_kyc_user import router as manual_kyc_user_router
from app.routers.manual_kyc_admin import router as manual_kyc_admin_router
from app.routers.reward_programs_admin import router as reward_programs_admin_router
from app.routers.reward_offers_admin import router as reward_offers_admin_router
from app.routers.reward_achievements_admin import router as reward_achievements_admin_router
from app.routers.investments_participant import router as investments_participant_router
from app.routers.investments_admin import router as investments_admin_router
from app.routers.payment_schedules_admin import router as payment_schedules_admin_router
from app.routers.pending_payments_admin import router as pending_payments_admin_router
from app.routers.closing_reports_admin import router as closing_reports_admin_router
from app.routers.payouts_admin import router as payouts_admin_router
from app.routers.payouts_partner import router as payouts_partner_router
from app.routers.payouts_participant import router as payouts_participant_router
from app.routers.admin_payout_recipients import router as admin_payout_recipients_router
from app.routers.payouts_admin_by_recipient import router as payouts_admin_by_recipient_router

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


API_DESCRIPTION = ""

app = FastAPI(
    title="Miracle World API",
    version="0.1.0",
    description=API_DESCRIPTION,
    swagger_ui_parameters={"persistAuthorization": True},
)
app.mount(
    "/profile_images",
    StaticFiles(directory="/var/www/miracleworldupload/profile_images"),
    name="profile_images",
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
            "role": "super_admin",
            "access_sections": "all",
            "status": "active",
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
            "introducerCommission": 0.0,
            "selfCommission": 0.0,
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
            "with repo supabase_tables.sql or run supabase_rename_legacy_id_columns.sql in Supabase SQL Editor. "
            "For portfolio fields run supabase_participants_portfolio_columns.sql, "
            "supabase_partners_mlm_portfolio_columns.sql, supabase_partners_total_business.sql, "
            "supabase_partners_self_commission_locked_by_parent_app.sql, "
            "supabase_upcoming_next_month_payment_columns.sql."
        )
    if isinstance(raw, dict) and raw.get("code") == "PGRST205":
        logger.warning(
            "PostgREST could not find a table (PGRST205). Create missing tables from repo SQL files "
            "(e.g. supabase_app_settings_table.sql, supabase_contact_queries_table.sql, "
            "supabase_fund_types_table.sql, supabase_fund_types_profit_capital_special_columns.sql, "
            "supabase_properties_table.sql, supabase_bank_details_table.sql, "
            "supabase_nominees_table.sql, supabase_manual_kyc_table.sql, "
            "supabase_manual_kyc_kyc_type_add_both.sql, supabase_reward_programs_tables.sql, "
            "supabase_investments_tables.sql, supabase_payouts_table.sql, "
            "supabase_participants_portfolio_columns.sql, supabase_participants_special_funds.sql, "
            "supabase_partners_mlm_portfolio_columns.sql, "
            "supabase_partner_commission_schedules.sql)."
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
app.include_router(participant_special_funds_admin_router, prefix="/admin")
app.include_router(fund_types_admin_router, prefix="/admin")
app.include_router(properties_admin_router, prefix="/admin")
app.include_router(bank_details_user_router)
app.include_router(bank_details_admin_router, prefix="/admin")
app.include_router(nominee_user_router)
app.include_router(nominee_admin_router, prefix="/admin")
app.include_router(manual_kyc_user_router)
app.include_router(manual_kyc_admin_router, prefix="/admin")
app.include_router(reward_programs_admin_router, prefix="/admin")
app.include_router(reward_offers_admin_router, prefix="/admin")
app.include_router(reward_achievements_admin_router, prefix="/admin")
app.include_router(investments_participant_router, prefix="/participant")
app.include_router(investments_admin_router, prefix="/admin")
app.include_router(payment_schedules_admin_router, prefix="/admin")
app.include_router(pending_payments_admin_router, prefix="/admin")
app.include_router(closing_reports_admin_router, prefix="/admin")
app.include_router(payouts_admin_router, prefix="/admin")
app.include_router(payouts_admin_by_recipient_router, prefix="/admin")
app.include_router(admin_payout_recipients_router, prefix="/admin")
app.include_router(payouts_partner_router, prefix="/partner")
app.include_router(payouts_participant_router, prefix="/participant")
app.include_router(participant_router)
app.include_router(partner_router)


@app.get("/")
def home():
    return {"message": "Miracle World API is running"}
