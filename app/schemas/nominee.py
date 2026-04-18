from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


NomineeStatus = Literal["Pending", "Verified", "Rejected"]


class NomineeCreate(BaseModel):
    """Create a nominee for the authenticated user (`userId` from token)."""

    model_config = ConfigDict(extra="forbid")

    fullName: str = Field(min_length=1, max_length=100)
    relation: str = Field(default="", max_length=50)
    dateOfBirth: Optional[date] = None
    gender: str = Field(default="", max_length=10)
    phoneNumber: str = Field(default="", max_length=15)
    email: str = Field(default="", max_length=100)
    aadhaarNumber: str = Field(default="", max_length=12)
    panNumber: str = Field(default="", max_length=10)
    address: str = Field(default="", max_length=5000)
    city: str = Field(default="", max_length=50)
    state: str = Field(default="", max_length=50)
    pincode: str = Field(default="", max_length=10)
    nomineeShare: Optional[Decimal] = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("100"),
    )
    isMinor: bool = False
    guardianName: str = Field(default="", max_length=100)


class NomineeUserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fullName: Optional[str] = Field(default=None, min_length=1, max_length=100)
    relation: Optional[str] = Field(default=None, max_length=50)
    dateOfBirth: Optional[date] = None
    gender: Optional[str] = Field(default=None, max_length=10)
    phoneNumber: Optional[str] = Field(default=None, max_length=15)
    email: Optional[str] = Field(default=None, max_length=100)
    aadhaarNumber: Optional[str] = Field(default=None, max_length=12)
    panNumber: Optional[str] = Field(default=None, max_length=10)
    address: Optional[str] = Field(default=None, max_length=5000)
    city: Optional[str] = Field(default=None, max_length=50)
    state: Optional[str] = Field(default=None, max_length=50)
    pincode: Optional[str] = Field(default=None, max_length=10)
    nomineeShare: Optional[Decimal] = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("100"),
    )
    isMinor: Optional[bool] = None
    guardianName: Optional[str] = Field(default=None, max_length=100)


class NomineeAdminStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: NomineeStatus
    rejectionReason: Optional[str] = Field(default=None, max_length=2000)


class NomineeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    nomineeId: int = Field(validation_alias=AliasChoices("nomineeId", "id"))
    userId: str
    fullName: str = Field(validation_alias=AliasChoices("fullName", "full_name"))
    relation: str = ""
    dateOfBirth: Optional[date] = Field(
        default=None, validation_alias=AliasChoices("dateOfBirth", "date_of_birth")
    )
    gender: str = ""
    phoneNumber: str = Field(
        default="", validation_alias=AliasChoices("phoneNumber", "phone_number")
    )
    email: str = ""
    aadhaarNumber: str = Field(
        default="", validation_alias=AliasChoices("aadhaarNumber", "aadhaar_number")
    )
    panNumber: str = Field(
        default="", validation_alias=AliasChoices("panNumber", "pan_number")
    )
    address: str = ""
    city: str = ""
    state: str = ""
    pincode: str = ""
    nomineeShare: Optional[Decimal] = Field(
        default=None, validation_alias=AliasChoices("nomineeShare", "nominee_share")
    )
    isMinor: bool = Field(default=False, validation_alias=AliasChoices("isMinor", "is_minor"))
    guardianName: str = Field(
        default="", validation_alias=AliasChoices("guardianName", "guardian_name")
    )
    status: NomineeStatus
    rejectionReason: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("rejectionReason", "rejection_reason"),
    )
    createdAt: datetime = Field(
        validation_alias=AliasChoices("createdAt", "created_at")
    )
    updatedAt: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("updatedAt", "updated_at")
    )
    verifiedBy: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("verifiedBy", "verified_by")
    )
    verifiedAt: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("verifiedAt", "verified_at")
    )
