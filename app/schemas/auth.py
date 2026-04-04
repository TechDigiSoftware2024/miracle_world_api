from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    phone: str
    mpin: str


class OtpSendRequest(BaseModel):
    phone: str
    otp_expiry: int = Field(default=5, ge=1, le=30)
    otp_length: int = Field(default=4, ge=4, le=6)
    otp: Optional[str] = None  # optional fixed OTP for testing if MSG91 template allows


class OtpRetryRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    phone: str
    retry_type: str = Field(
        default="text",
        validation_alias=AliasChoices("retrytype", "retryType"),
    )


class OtpLoginRequest(BaseModel):
    """Verify OTP with MSG91, then issue the same JWT as POST /login (phone-only match)."""

    phone: str
    otp: str = Field(min_length=4)


class OtpOperationResponse(BaseModel):
    success: bool
    message: str
    request_id: Optional[str] = None
    code: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    userId: str
    name: str


class AdminPhoneCheckRequest(BaseModel):
    phone: str


class AdminPhoneCheckResponse(BaseModel):
    is_admin: bool
