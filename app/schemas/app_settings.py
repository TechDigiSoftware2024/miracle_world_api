from datetime import datetime
from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class AppSettingsResponse(BaseModel):
    """Singleton app/company defaults (id is always 1)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int = 1
    defaultPartnerId: str = Field(
        validation_alias=AliasChoices("defaultPartnerId", "default_partner_id")
    )
    defaultParticipantId: str = Field(
        validation_alias=AliasChoices("defaultParticipantId", "default_participant_id")
    )
    companyName: str = Field(validation_alias=AliasChoices("companyName", "company_name"))
    companyEmail: str = Field(validation_alias=AliasChoices("companyEmail", "company_email"))
    companyPhone: str = Field(validation_alias=AliasChoices("companyPhone", "company_phone"))
    companyAddress: str = Field(
        validation_alias=AliasChoices("companyAddress", "company_address")
    )
    updatedAt: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("updatedAt", "updated_at"),
    )
    createdAt: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("createdAt", "created_at"),
    )


class AppSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defaultPartnerId: Optional[str] = None
    defaultParticipantId: Optional[str] = None
    companyName: Optional[str] = None
    companyEmail: Optional[str] = None
    companyPhone: Optional[str] = None
    companyAddress: Optional[str] = None
