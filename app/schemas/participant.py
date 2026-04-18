from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional


class ParticipantResponse(BaseModel):
    participantId: str = Field(validation_alias=AliasChoices("participantId", "investorId"))
    name: str
    phone: str
    email: str
    address: str
    introducer: str
    mpin: str
    profileImage: Optional[str] = None
    status: str
    totalInvestment: float
    offeredValues: Optional[str] = None
    lastVisit: Optional[datetime] = None
    lastUpdated: Optional[datetime] = None
    createdAt: datetime


class ParticipantUpdate(BaseModel):
    """All participant fields except phone and participantId may be updated."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    introducer: Optional[str] = None
    mpin: Optional[str] = None
    profileImage: Optional[str] = None
    status: Optional[str] = None
    totalInvestment: Optional[float] = None
    offeredValues: Optional[str] = None
    lastVisit: Optional[datetime] = None
    lastUpdated: Optional[datetime] = None


class PartnerSearchResponse(BaseModel):
    """Partner fields returned to participants when searching introducers."""

    model_config = ConfigDict(populate_by_name=True)

    partnerId: str = Field(validation_alias=AliasChoices("partnerId", "agentId"))
    name: str
    phone: str
