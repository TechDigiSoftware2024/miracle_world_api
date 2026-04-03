from fastapi import FastAPI

from app.db.database import supabase
from app.routers.request import router as request_router
from app.routers.unified_login import router as unified_login_router
from app.routers.admin import router as admin_router
from app.routers.participant import router as participant_router
from app.routers.partner import router as partner_router

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


def seed_defaults():
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
        }).execute()


seed_defaults()

app.include_router(request_router)
app.include_router(unified_login_router)
app.include_router(admin_router)
app.include_router(participant_router)
app.include_router(partner_router)


@app.get("/")
def home():
    return {"message": "Miracle World API is running"}
