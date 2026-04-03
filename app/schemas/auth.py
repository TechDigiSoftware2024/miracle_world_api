from pydantic import BaseModel


class LoginRequest(BaseModel):
    phone: str
    mpin: str


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
