from fastapi import APIRouter, HTTPException, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.schemas.contact import ContactUsRequest, ContactUsResponse
from app.services.contact_email import send_contact_notification, smtp_configured
from app.utils.supabase_errors import format_api_error

router = APIRouter(tags=["Public"])


@router.post("/contact", response_model=ContactUsResponse, status_code=status.HTTP_201_CREATED)
def contact_us(payload: ContactUsRequest):
    """
    Public contact form: stores row in `contact_queries` and optionally emails **CONTACT_NOTIFY_TO**
    when SMTP env vars are set.
    """
    try:
        result = (
            supabase.table("contact_queries")
            .insert({
                "name": payload.name.strip(),
                "email": payload.email.strip(),
                "phone": payload.phone,
                "message": payload.message.strip(),
            })
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e

    row = result.data[0] if result.data else None
    if not row or row.get("id") is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save contact query.",
        )

    qid = int(row["id"])
    email_sent = send_contact_notification(
        name=payload.name.strip(),
        email=payload.email.strip(),
        phone=payload.phone,
        message=payload.message.strip(),
    )

    msg = "Your message was received. We will get back to you soon."
    if smtp_configured() and not email_sent:
        msg = (
            "Your message was saved. We could not send the notification email; "
            "our team will still see it in the system."
        )
    elif not smtp_configured():
        msg = (
            "Your message was saved successfully. "
            "Email notification is not configured on the server yet."
        )

    return ContactUsResponse(
        id=qid,
        email_sent=email_sent,
        message=msg,
    )
