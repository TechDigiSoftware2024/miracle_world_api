import re

from pydantic import BaseModel, Field, field_validator


class ContactUsRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    phone: str = Field(min_length=10, max_length=15)
    message: str = Field(default="", max_length=5000)

    @field_validator("email")
    @classmethod
    def email_basic(cls, v: str) -> str:
        s = v.strip()
        if "@" not in s or "." not in s.split("@")[-1]:
            raise ValueError("Invalid email address")
        return s

    @field_validator("phone")
    @classmethod
    def phone_digits(cls, v: str) -> str:
        d = re.sub(r"\D", "", v.strip())
        if len(d) == 12 and d.startswith("91"):
            d = d[2:]
        if len(d) != 10 or not d.isdigit():
            raise ValueError("Phone must be 10 digits (India)")
        return d


class ContactUsResponse(BaseModel):
    success: bool = True
    id: int
    email_sent: bool
    message: str
