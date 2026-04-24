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
from app.routers.investments_participant import router as investments_participant_router
from app.routers.investments_admin import router as investments_admin_router
from app.routers.payment_schedules_admin import router as payment_schedules_admin_router
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


API_DESCRIPTION = """
## Flow
1. **Contact (public)**: `POST /contact` with `name`, `email`, `phone` (10 digits), optional `message` — saves to Supabase `contact_queries`; optional SMTP notifies **CONTACT_NOTIFY_TO**.
2. **App settings**: Public `GET /settings` (company + default participant/partner IDs). Admin `GET /admin/settings` and `PATCH /admin/settings` to edit the same singleton row.
3. **New users** call `POST /request`, then `GET /track-request/{phone}` (each item includes **id**). Public `DELETE /request/{request_id}?phone=...` removes a request when **phone** matches that row.
4. **Optional**: `POST /check-admin-phone` with `{"phone":"..."}` returns `is_admin` so the UI can branch before mpin.
5. **Login (MPIN)**: `POST /login` — phone + **mpin**; tries **admin → participant → partner**. Use `role` in the response for the app shell. **Swap role (participant ↔ partner)**: `POST /swap-role` with **Bearer** token when the same phone has **both** participant and partner rows — returns a new JWT for the other role and revokes the current token.
6. **Login (OTP / MSG91)**: `POST /otp/send` → `POST /otp/login` with phone + **otp** (same JWT as MPIN login). Optional `POST /otp/retry`. Configure `MSG91_AUTH_KEY` and `MSG91_TEMPLATE_ID` on the server; Flutter should call **these** endpoints instead of embedding the MSG91 auth key in the app.
7. **Protected routes** need header: `Authorization: Bearer <access_token>` from login.
8. In **Swagger UI**, click **Authorize**, paste the token only (not the word Bearer), then call admin endpoints.
9. **Approve request**: `PUT /admin/request/{request_id}/approve` creates a row in **participants** or **partners** based on the request role and sets a new mpin on the request record.
10. **Admin directory**: Participants/partners/contact-queries/settings; user `DELETE`/`PATCH` by **`participantId`** / **`partnerId`**. **Fund types**: admin CRUD under `/admin/fund-types` (optional query **`isSpecial`** to list only special funds; body field **`duration`** is total months only; **`isProfitCapitalPerMonth`**, **`isSpecial`** booleans); public `GET /fund-types` (active only — prefer participant-scoped list in apps). **Special funds**: SQL `supabase_participants_special_funds.sql` adds **`participants.isEligible`** and **`participant_special_funds`**. Admin **`POST /admin/participants/special-funds/assign`** (body **`participantIds`**, **`fundTypeIds`**, optional **`setIsEligible`**) and **`POST .../remove`**; **`GET /admin/participants/special-funds/{participantId}`**. **`PATCH /admin/participants/{participantId}`** may set **`isEligible`**. Participants: **`GET /participant/fund-types`** (Bearer) returns non-special active funds plus assigned special funds when eligible; profile includes **`isEligible`** and **`eligibleSpecialFundIds`**. **Properties**: admin `GET|POST /admin/properties`, `GET|PATCH|DELETE /admin/properties/{id}`; **public (no token)** `GET /properties` (optional `?status=&type=&purpose=&city=`) and `GET /properties/{id}` for participant dashboards.
11. **Self profile**: `PATCH /participant/profile` — only **`name`**, **`email`**, **`address`** (no phone, mpin, financials, or portfolio fields; those are server-managed). **`PATCH /admin/participants/{participantId}`** — same fields plus optional **`mpin`**. Participant portfolio columns (**`activeInvestmentsCount`**, **`totalPrincipalAmount`**, **`pendingScheduleAmount`**, **`schedulePaidAmount`**, **`payoutsPaidAmount`**, **`totalPortfolioValue`**, **`portfolioUpdatedAt`**) are recalculated when investments, payment schedule lines, or participant payouts change. SQL: `supabase_participants_portfolio_columns.sql`. **Partners** (SQL: `supabase_partners_mlm_portfolio_columns.sql`): **`introducerCommission`**, MLM aggregates (**`portfolioAmount`**, **`paidAmount`**, **`pendingAmount`**, **`perMonthPendingAmount`**, **`participantInvestedTotal`**, **`introducerCommissionAmount`**, **`selfEarningAmount`**, **`teamEarningAmount`**, **`portfolioUpdatedAt`**). Partner app: **`GET /partner/account`** & **`GET /partner/profile`** — basic account only (no MPIN/financials); **`PATCH /partner/profile`** — **`name`**, **`email`**, **`location`** or **`address`** only; **`GET /partner/investments`** — investments with **`agentId`** = self; **`GET /partner/team`** — downline partner tree (children only, no parent); **`POST /partner/team/{childPartnerId}/commission`** — parent sets child **`selfCommission`** (≤ parent **`selfCommission`**); child **`introducerCommission`** = parent.self − child.self (0 if equal). Admin: **`GET /admin/partners/{partnerId}`** (full row); **`PATCH /admin/partners/{partnerId}`** — **`name`**, **`email`**, **`location`/`address`**, **`selfCommission`**, **`mpin`** (rejects patch if any direct child’s **`selfCommission`** exceeds new cap; syncs children **`introducerCommission`**); **`GET /admin/partners/{partnerId}/team`**, **`GET /admin/partners/{partnerId}/investments`**. **Participant partner search**: `GET /participant/partners/search` with exactly one of **`name`**, **`partnerId`**, **`phone`**.
12. **Bank details**: User `GET /bank-details/user/{userId}` (participant/partner own `userId` from login, or admin), `POST /bank-details`, `PUT /bank-details/{id}`. Admin `GET /admin/bank-details/pending`, `GET /admin/bank-details/{id}`, `PATCH /admin/bank-details/{id}/status`. Create table from `supabase_bank_details_table.sql`.
13. **Nominees**: User `GET /nominees/user/{userId}`, `POST /nominees`, `PUT /nominees/{id}`. Admin `GET /admin/nominees`, `GET /admin/nominees/pending`, `GET /admin/nominees/user/{userId}`, `GET /admin/nominees/{id}`, `PATCH /admin/nominees/{id}/status`, `DELETE /admin/nominees/{id}`. Create table from `supabase_nominees_table.sql`.
14. **Manual KYC**: User `GET /manual-kyc/user/{userId}`, `POST /manual-kyc` (`kycType`: **PAN**, **AADHAAR**, or **Both** + document URLs), `PUT /manual-kyc/{id}`. Admin `GET /admin/manual-kyc`, `GET /admin/manual-kyc/pending`, `GET /admin/manual-kyc/user/{userId}`, `GET /admin/manual-kyc/{id}`, `PATCH /admin/manual-kyc/{id}/status`, `DELETE /admin/manual-kyc/{id}`. Schema: `supabase_manual_kyc_table.sql`; existing DBs: `supabase_manual_kyc_kyc_type_add_both.sql`.
15. **Reward programs**: Admin CRUD `GET|POST /admin/reward-programs`, `GET|PATCH|DELETE /admin/reward-programs/{id}`; offers `GET /admin/reward-offers?program_id=` `POST|GET|PATCH|DELETE /admin/reward-offers/...`. Partner `GET /partner/reward-programs` (active programs + offers). SQL: `supabase_reward_programs_tables.sql`.
16. **Investments**: Typical flow **Processing** (create) → **Pending Approval** (after participant `PATCH` with document URL) → **Active** (admin `PATCH .../status`; admin may activate from **Processing** or **Pending Approval** without documents). Then **Matured** when all schedule lines are **paid**. **Completed** remains for manual closure if needed. Participant `POST|GET /participant/investments`, `GET /participant/investments/{investmentId}`, `PATCH` (document URL), `GET .../payment-schedules`. Admin `GET|POST /admin/investments`, `GET /admin/investments/stats` (admin dashboard: portfolio totals, app participant/partner counts, pending **user_requests**, per–fund-type investment and user-investor counts; optional `fund_type_id` on the fund list), `GET /admin/investments/pending` (**Processing** + **Pending Approval**), `?participant_id=`, `PATCH /admin/investments/{id}`, `PATCH /admin/investments/{id}/status`, `DELETE`, `GET .../payment-schedules`; `PATCH /admin/payment-schedules/{id}` (line **paid**/…). SQL: `supabase_investments_tables.sql`; existing DBs: `supabase_investment_status_workflow_migration.sql`.
17. **Payouts**: Table `supabase_payouts_table.sql` (existing DBs: `supabase_payouts_level_depth_migration.sql`) — **payoutId**, **userId**, **recipientType** (participant | partner), **amount**, **status** (pending, processing, paid, failed, cancelled), **paymentMethod** (BANK, IMPS/NEFT, CASH), optional **transactionId** / **investmentId**, **payoutDate**, **remarks**, **payoutType** (commission, monthly_income, extra_income), **createdBy** (admin | automatic), **createdByAdminId** when created by admin, optional **levelDepth** (1–100, **partner** MLM downline only; `null` for participants). Admin: `GET|POST /admin/payouts`, `GET /admin/payouts/{payoutId}`, `PATCH|DELETE /admin/payouts/{payoutId}`; list search/filter: `q`, `payoutStatus`, `payoutType`, `paymentMethod`, `userId`, `recipientType`, `payoutDateFrom`, `payoutDateTo`, `levelDepth`. **Per-user (detail screens)**: `GET /admin/participants/{participantId}/payouts`, `GET /admin/partners/{partnerId}/payouts` — 404 if that participant/partner does not exist; same list filters as the global **GET /admin/payouts** (partner route includes `levelDepth`). **Recipient picker** (admin, for create form): `GET /admin/payout-recipients/participants` and `GET /admin/payout-recipients/partners` — query **id** (exact id), **name** (partial), **phone** (exact 10-digit); at least one required; filters are AND; optional `limit` (default 30, max 100). Partner: `GET /partner/payouts` (same search params, only own rows). Participant: `GET /participant/payouts` (same without `levelDepth` filter, only own rows).
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
            "introducerCommission": 0.0,
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
            "(e.g. supabase_app_settings_table.sql, supabase_contact_queries_table.sql, "
            "supabase_fund_types_table.sql, supabase_fund_types_profit_capital_special_columns.sql, "
            "supabase_properties_table.sql, supabase_bank_details_table.sql, "
            "supabase_nominees_table.sql, supabase_manual_kyc_table.sql, "
            "supabase_manual_kyc_kyc_type_add_both.sql, supabase_reward_programs_tables.sql, "
            "supabase_investments_tables.sql, supabase_payouts_table.sql, "
            "supabase_participants_portfolio_columns.sql, supabase_participants_special_funds.sql, "
            "supabase_partners_mlm_portfolio_columns.sql)."
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
app.include_router(investments_participant_router, prefix="/participant")
app.include_router(investments_admin_router, prefix="/admin")
app.include_router(payment_schedules_admin_router, prefix="/admin")
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
