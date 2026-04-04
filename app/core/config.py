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

# Contact form: optional SMTP to notify info@… (see app/services/contact_email.py)
CONTACT_NOTIFY_TO = (os.getenv("CONTACT_NOTIFY_TO") or "info@miracleworldllp.com").strip()
SMTP_HOST = (os.getenv("SMTP_HOST") or "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT") or "587")
SMTP_USER = (os.getenv("SMTP_USER") or "").strip()
SMTP_PASSWORD = (os.getenv("SMTP_PASSWORD") or "").strip()
SMTP_FROM = (os.getenv("SMTP_FROM") or "").strip() or None
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")
