from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional


class PartnerResponse(BaseModel):
    partnerId: str = Field(validation_alias=AliasChoices("partnerId", "agentId"))
    name: str
    phone: str
    email: str
    location: str
    introducer: str
    mpin: str
    profileImage: str
    status: str
    commission: float
    selfCommission: float
    selfProfit: float
    generatedProfitByTeam: float
    totalDeals: int
    totalTeamMembers: int
    createdAt: datetime


class PartnerUpdate(BaseModel):
    """All partner fields except phone and partnerId may be updated."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    email: Optional[str] = None
    location: Optional[str] = None
    introducer: Optional[str] = None
    mpin: Optional[str] = None
    profileImage: Optional[str] = None
    status: Optional[str] = None
    commission: Optional[float] = None
    selfCommission: Optional[float] = None
    selfProfit: Optional[float] = None
    generatedProfitByTeam: Optional[float] = None
    totalDeals: Optional[int] = None
    totalTeamMembers: Optional[int] = None
