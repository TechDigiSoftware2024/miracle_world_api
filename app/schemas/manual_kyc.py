from datetime import datetime
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


ManualKycType = Literal["PAN", "AADHAAR"]
ManualKycStatus = Literal["Pending", "Verified", "Rejected"]


class ManualKycCreate(BaseModel):
    """Submit PAN or Aadhaar KYC with a document URL (e.g. Supabase Storage public URL)."""

    model_config = ConfigDict(extra="forbid")

    kycType: ManualKycType
    panNumber: str = Field(default="", max_length=20)
    panFullName: str = Field(default="", max_length=200)
    panDocumentUrl: str = Field(default="", max_length=4096)
    aadhaarNumber: str = Field(default="", max_length=20)
    aadhaarFullName: str = Field(default="", max_length=200)
    aadhaarDocumentUrl: str = Field(default="", max_length=4096)

    @model_validator(mode="after")
    def validate_fields_for_kyc_type(self):
        if self.kycType == "PAN":
            if not self.panNumber.strip():
                raise ValueError("panNumber is required when kycType is PAN")
            if not self.panDocumentUrl.strip():
                raise ValueError("panDocumentUrl is required when kycType is PAN")
        else:
            if not self.aadhaarNumber.strip():
                raise ValueError("aadhaarNumber is required when kycType is AADHAAR")
            if not self.aadhaarDocumentUrl.strip():
                raise ValueError("aadhaarDocumentUrl is required when kycType is AADHAAR")
        return self


class ManualKycUserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kycType: Optional[ManualKycType] = None
    panNumber: Optional[str] = Field(default=None, max_length=20)
    panFullName: Optional[str] = Field(default=None, max_length=200)
    panDocumentUrl: Optional[str] = Field(default=None, max_length=4096)
    aadhaarNumber: Optional[str] = Field(default=None, max_length=20)
    aadhaarFullName: Optional[str] = Field(default=None, max_length=200)
    aadhaarDocumentUrl: Optional[str] = Field(default=None, max_length=4096)


class ManualKycAdminStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ManualKycStatus
    rejectionReason: Optional[str] = Field(default=None, max_length=2000)


class ManualKycResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    manualKycId: int = Field(validation_alias=AliasChoices("manualKycId", "id"))
    userId: str
    kycType: ManualKycType = Field(validation_alias=AliasChoices("kycType", "kyc_type"))
    panNumber: str = Field(default="", validation_alias=AliasChoices("panNumber", "pan_number"))
    panFullName: str = Field(
        default="", validation_alias=AliasChoices("panFullName", "pan_full_name")
    )
    panDocumentUrl: str = Field(
        default="", validation_alias=AliasChoices("panDocumentUrl", "pan_document_url")
    )
    aadhaarNumber: str = Field(
        default="", validation_alias=AliasChoices("aadhaarNumber", "aadhaar_number")
    )
    aadhaarFullName: str = Field(
        default="", validation_alias=AliasChoices("aadhaarFullName", "aadhaar_full_name")
    )
    aadhaarDocumentUrl: str = Field(
        default="", validation_alias=AliasChoices("aadhaarDocumentUrl", "aadhaar_document_url")
    )
    status: ManualKycStatus
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
