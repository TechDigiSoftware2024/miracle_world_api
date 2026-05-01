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
    upcomingNetNextMonthPayment: float = Field(
        default=0.0,
        description=(
            "Sum of pending/due payment_schedules with payoutDate in the next UTC calendar month; "
            "recalculated with portfolio fields."
        ),
    )
    offeredValues: Optional[str] = None
    lastVisit: Optional[datetime] = None
    lastUpdated: Optional[datetime] = None
    createdAt: datetime
    isEligible: bool = Field(
        default=False,
        description="When true, participant may see assigned special fund types in fund-type lists.",
    )
    eligibleSpecialFundIds: list[int] = Field(
        default_factory=list,
        description="fund_types.id values explicitly assigned to this participant (special funds only).",
    )

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
            ("upcomingNetNextMonthPayment", 0),
        ):
            if data.get(k) is None:
                data[k] = v
        if data.get("isEligible") is None:
            data["isEligible"] = False
        if data.get("eligibleSpecialFundIds") is None:
            data["eligibleSpecialFundIds"] = []
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
    isEligible: Optional[bool] = Field(
        default=None,
        description="Whether the participant is eligible for assigned special funds in app fund lists.",
    )


class PartnerSearchResponse(BaseModel):
    """Partner fields returned to participants when searching introducers."""

    model_config = ConfigDict(populate_by_name=True)

    partnerId: str = Field(validation_alias=AliasChoices("partnerId", "agentId"))
    name: str
    phone: str
