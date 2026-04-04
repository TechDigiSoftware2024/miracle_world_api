import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import (
    CONTACT_NOTIFY_TO,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_TLS,
    SMTP_USER,
)

logger = logging.getLogger(__name__)


def smtp_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD and CONTACT_NOTIFY_TO)


def _build_body(*, name: str, email: str, phone: str, message: str) -> str:
    msg_text = message.strip() if message.strip() else "No message provided"
    submitted = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"""🏠 MIRACLE WORLD - New Contact Query
👤 Name: {name}
📧 Email: {email}
📱 Phone: +91 {phone}
💬 Message: {msg_text}
Submitted on: {submitted}

Miracle World Real Estate LLP
906-907, Gera Imperium Alpha, Pune
info@miracleworldllp.com | +91 6204599636
"""


def send_contact_notification(
    *,
    name: str,
    email: str,
    phone: str,
    message: str,
) -> bool:
    """
    Notify CONTACT_NOTIFY_TO via SMTP. Returns True if sent, False if skipped/failed.
    """
    if not smtp_configured():
        logger.info("SMTP not configured; contact saved without email notify.")
        return False

    from_addr = (SMTP_FROM or SMTP_USER).strip()
    subject = f"🏠 New Contact Query - {name}"
    body = _build_body(name=name, email=email, phone=phone, message=message)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Miracle World API", from_addr))
    msg["To"] = CONTACT_NOTIFY_TO
    msg["Reply-To"] = email
    msg.set_content(body, charset="utf-8")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            if SMTP_USE_TLS:
                server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception:
        logger.exception("Failed to send contact notification email")
        return False
