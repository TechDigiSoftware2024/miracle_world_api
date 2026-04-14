from datetime import datetime
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


BankDetailStatus = Literal["Pending", "Approved", "Rejected"]


class BankDetailCreate(BaseModel):
    """Create bank details for the authenticated user (`userId` comes from the token)."""

    model_config = ConfigDict(extra="forbid")

    holderName: str = Field(min_length=1, max_length=300)
    bankName: str = Field(min_length=1, max_length=300)
    accountNumber: str = Field(min_length=1, max_length=64)
    ifscCode: str = Field(min_length=1, max_length=20)
    upiId: str = Field(default="", max_length=200)
    branchName: str = Field(default="", max_length=300)
    accountType: str = Field(default="", max_length=100)


class BankDetailUserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holderName: Optional[str] = Field(default=None, min_length=1, max_length=300)
    bankName: Optional[str] = Field(default=None, min_length=1, max_length=300)
    accountNumber: Optional[str] = Field(default=None, min_length=1, max_length=64)
    ifscCode: Optional[str] = Field(default=None, min_length=1, max_length=20)
    upiId: Optional[str] = Field(default=None, max_length=200)
    branchName: Optional[str] = Field(default=None, max_length=300)
    accountType: Optional[str] = Field(default=None, max_length=100)


class BankDetailAdminStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: BankDetailStatus
    rejectionReason: Optional[str] = Field(default=None, max_length=2000)


class BankDetailResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    bankDetailId: int = Field(validation_alias=AliasChoices("bankDetailId", "id"))
    userId: str
    holderName: str = Field(validation_alias=AliasChoices("holderName", "holder_name"))
    bankName: str = Field(validation_alias=AliasChoices("bankName", "bank_name"))
    accountNumber: str = Field(
        validation_alias=AliasChoices("accountNumber", "account_number")
    )
    ifscCode: str = Field(validation_alias=AliasChoices("ifscCode", "ifsc_code"))
    upiId: str = Field(default="", validation_alias=AliasChoices("upiId", "upi_id"))
    branchName: str = Field(
        default="", validation_alias=AliasChoices("branchName", "branch_name")
    )
    accountType: str = Field(
        default="", validation_alias=AliasChoices("accountType", "account_type")
    )
    status: BankDetailStatus
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
