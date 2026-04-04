from fastapi import APIRouter, HTTPException, status

from app.schemas.auth import (
    OtpLoginRequest,
    OtpOperationResponse,
    OtpRetryRequest,
    OtpSendRequest,
    TokenResponse,
)
from app.services.msg91 import MSG91Error, msg91_retry_otp, msg91_send_otp, msg91_verify_otp
from app.services.phone_auth import issue_token_for_phone
from app.utils.phone_normalize import format_phone_msg91, is_plausible_in_mobile

router = APIRouter(prefix="/otp", tags=["OTP / MSG91"])


@router.post("/send", response_model=OtpOperationResponse)
def otp_send(payload: OtpSendRequest):
    """Send OTP via MSG91 (auth key stays on server)."""
    if not is_plausible_in_mobile(payload.phone):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid phone number",
        )
    mobile = format_phone_msg91(payload.phone)
    try:
        result = msg91_send_otp(
            mobile,
            otp=payload.otp,
            otp_expiry=payload.otp_expiry,
            otp_length=payload.otp_length,
        )
        return OtpOperationResponse(
            success=True,
            message=result["message"],
            request_id=result.get("request_id"),
        )
    except MSG91Error as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            if "not configured" in str(e).lower()
            else status.HTTP_400_BAD_REQUEST,
            detail={"message": str(e), "code": e.code},
        ) from e


@router.post("/retry", response_model=OtpOperationResponse)
def otp_retry(payload: OtpRetryRequest):
    """Resend OTP (MSG91 retry — text/voice per retry_type)."""
    if not is_plausible_in_mobile(payload.phone):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid phone number",
        )
    mobile = format_phone_msg91(payload.phone)
    try:
        result = msg91_retry_otp(mobile, retry_type=payload.retry_type)
        return OtpOperationResponse(
            success=True,
            message=result["message"],
            request_id=result.get("request_id"),
        )
    except MSG91Error as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            if "not configured" in str(e).lower()
            else status.HTTP_400_BAD_REQUEST,
            detail={"message": str(e), "code": e.code},
        ) from e


@router.post("/login", response_model=TokenResponse)
def otp_login(payload: OtpLoginRequest):
    """
    Verify OTP with MSG91, then return the same JWT as `POST /login` (admin → participant → partner).
    Use `POST /login` with mpin for password-style login.
    """
    if not is_plausible_in_mobile(payload.phone):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid phone number",
        )
    mobile = format_phone_msg91(payload.phone)
    try:
        msg91_verify_otp(mobile, payload.otp.strip())
    except MSG91Error as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            if "not configured" in str(e).lower()
            else status.HTTP_401_UNAUTHORIZED,
            detail={"message": str(e), "code": e.code},
        ) from e

    token = issue_token_for_phone(payload.phone, mpin=None)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found for this phone. Sign up or use an approved account.",
        )
    return token
