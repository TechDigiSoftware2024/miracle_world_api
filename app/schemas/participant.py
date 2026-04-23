from datetime import datetime
from typing import Any, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class ParticipantResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    participantId: str = Field(validation_alias=AliasChoices("participantId", "investorId"))
    name: str
    phone: str
    email: str
    address: str
    introducer: str
    mpin: str
    profileImage: Optional[str] = None
    status: str
    totalInvestment: float = Field(
        description="Sum of principal; kept in sync with totalPrincipalAmount by the server.",
    )
    activeInvestmentsCount: int = 0
    totalPrincipalAmount: float = 0.0
    pendingScheduleAmount: float = 0.0
    schedulePaidAmount: float = 0.0
    payoutsPaidAmount: float = 0.0
    totalPortfolioValue: float = 0.0
    portfolioUpdatedAt: Optional[datetime] = None
    offeredValues: Optional[str] = None
    lastVisit: Optional[datetime] = None
    lastUpdated: Optional[datetime] = None
    createdAt: datetime

    @model_validator(mode="before")
    @classmethod
    def _backfill_portfolio_from_total_investment(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("totalPrincipalAmount") is None and "totalInvestment" in data:
            data["totalPrincipalAmount"] = data.get("totalInvestment")
        for k, v in (
            ("activeInvestmentsCount", 0),
            ("pendingScheduleAmount", 0),
            ("schedulePaidAmount", 0),
            ("payoutsPaidAmount", 0),
            ("totalPortfolioValue", 0),
        ):
            if data.get(k) is None:
                data[k] = v
        return data


class ParticipantProfilePatch(BaseModel):
    """Participant self-serve: name, email, address only. Financial fields are recalculated server-side."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    email: Optional[str] = None
    address: Optional[str] = None


class AdminParticipantProfilePatch(BaseModel):
    """Admin: same as participant plus optional mpin. No financial or portfolio fields."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    email: Optional[str] = None
    address: Optional[str] = None
    mpin: Optional[str] = Field(default=None, min_length=4, max_length=32)


class PartnerSearchResponse(BaseModel):
    """Partner fields returned to participants when searching introducers."""

    model_config = ConfigDict(populate_by_name=True)

    partnerId: str = Field(validation_alias=AliasChoices("partnerId", "agentId"))
    name: str
    phone: str
