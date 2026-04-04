from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_KEY must be set. "
        "Grab them from Supabase Dashboard > Settings > API."
    )

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "fallback-secret-change-me")
JWT_ALGORITHM = "HS256"

# MSG91 OTP (optional — leave empty to disable /otp/* routes except clear errors)
MSG91_AUTH_KEY = (os.getenv("MSG91_AUTH_KEY") or "").strip()
MSG91_TEMPLATE_ID = (os.getenv("MSG91_TEMPLATE_ID") or "").strip()
MSG91_BASE_URL = (
    os.getenv("MSG91_BASE_URL") or "https://control.msg91.com/api/v5"
).strip()
