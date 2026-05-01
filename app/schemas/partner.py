from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field, model_validator


class PartnerResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    partnerId: str = Field(validation_alias=AliasChoices("partnerId", "agentId"))
    name: str
    phone: str
    email: str
    location: str
    introducer: str
    mpin: str
    profileImage: str
    status: str
    introducerCommission: float = Field(
        default=0,
        validation_alias=AliasChoices("introducerCommission", "commission"),
        description="Introducer commission rate on downline principal (percentage points, e.g. 5 means 5%).",
    )
    selfCommission: float = 0
    totalDeals: int = Field(
        default=0,
        description="Count of investments with agentId=this partner and status Active, Matured, or Completed.",
    )
    totalTeamMembers: int = Field(
        default=0,
        description="Total downline partners (all depths) where introducer chain leads to this partner.",
    )
    createdAt: datetime
    portfolioAmount: float = Field(
        default=0,
        description=(
            "Total **paid** partner commission for this beneficiary: sum of partner_commission_schedules "
            "with status paid (level 0 + upline). Accruals still pending/due are not included."
        ),
    )
    paidAmount: float = Field(
        default=0,
        description=(
            "Same as portfolioAmount here: total **paid** commission accruals from partner_commission_schedules."
        ),
    )
    pendingAmount: float = Field(
        default=0,
        description=(
            "Sum of partner_commission_schedules with status pending or due for this beneficiary "
            "(commission not yet marked paid)."
        ),
    )
    participantInvestedTotal: float = Field(
        default=0,
        description="Sum of investedAmount on downline investments (agentId=this partner) in Active, Matured, Completed, or Pending Approval.",
    )
    introducerCommissionAmount: float = Field(
        default=0,
        description="participantInvestedTotal × introducerCommission / 100 (recalculated server-side).",
    )
    selfEarningAmount: float = Field(
        default=0,
        description=(
            "Sum of **paid** partner_commission_schedules.amount for this partner as beneficiary with level 0 "
            "(direct agent share)."
        ),
    )
    teamEarningAmount: float = Field(
        default=0,
        description=(
            "Sum of **paid** partner_commission_schedules.amount for this partner with level ≥ 1 "
            "(introducer/upline share)."
        ),
    )
    portfolioUpdatedAt: Optional[datetime] = None
    upcomingNetNextMonthPayment: float = Field(
        default=0.0,
        description=(
            "Sum of pending/due partner_commission_schedules for this partner as beneficiary "
            "with payoutDate in the next UTC calendar month; recalculated with portfolio fields."
        ),
    )

    @computed_field
    @property
    def selfProfit(self) -> float:
        """API alias for ``selfEarningAmount`` (paid commission, level 0; not stored on ``partners``)."""

        return self.selfEarningAmount

    @computed_field
    @property
    def generatedProfitByTeam(self) -> float:
        """API alias for ``teamEarningAmount`` (paid commission, level ≥ 1; not stored on ``partners``)."""

        return self.teamEarningAmount

    @model_validator(mode="before")
    @classmethod
    def _backfill_partner_financial_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if d.get("introducerCommission") is None and d.get("commission") is not None:
            d["introducerCommission"] = d.get("commission")
        for key, default in (
            ("portfolioAmount", 0),
            ("paidAmount", 0),
            ("pendingAmount", 0),
            ("participantInvestedTotal", 0),
            ("introducerCommissionAmount", 0),
            ("selfEarningAmount", 0),
            ("teamEarningAmount", 0),
            ("upcomingNetNextMonthPayment", 0),
            ("selfCommission", 0),
            ("totalDeals", 0),
            ("totalTeamMembers", 0),
        ):
            if d.get(key) is None:
                d[key] = default
        return d


class PartnerUpdate(BaseModel):
    """Legacy broad partner patch (prefer AdminPartnerProfilePatch / PartnerSelfProfilePatch)."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    email: Optional[str] = None
    location: Optional[str] = None
    introducer: Optional[str] = None
    mpin: Optional[str] = None
    profileImage: Optional[str] = None
    status: Optional[str] = None
    introducerCommission: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices("introducerCommission", "commission"),
    )
    selfCommission: Optional[float] = None
    totalDeals: Optional[int] = None
    totalTeamMembers: Optional[int] = None


class PartnerAccountBasicResponse(BaseModel):
    """Partner app account screen: no MPIN, no financial / MLM aggregates."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    partnerId: str = Field(validation_alias=AliasChoices("partnerId", "agentId"))
    name: str
    phone: str
    email: str
    location: str = Field(description="Address / location (same column as DB `location`).")
    profileImage: str = ""
    status: str
    createdAt: datetime


class PartnerSelfProfilePatch(BaseModel):
    """Partner self-service: name, email, address/location only."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    email: Optional[str] = None
    location: Optional[str] = Field(
        default=None,
        max_length=2000,
        validation_alias=AliasChoices("location", "address"),
        description="Physical or mailing address (stored as `location`).",
    )


class AdminPartnerProfilePatch(BaseModel):
    """Admin-only partner profile fields."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    email: Optional[str] = None
    location: Optional[str] = Field(
        default=None,
        max_length=2000,
        validation_alias=AliasChoices("location", "address"),
    )
    selfCommission: Optional[float] = Field(
        default=None,
        ge=0,
        description="Partner's own commission % ceiling; children's selfCommission cannot exceed this.",
    )
    mpin: Optional[str] = Field(default=None, min_length=4, max_length=32)


class PartnerTeamMemberNode(BaseModel):
    """One node in the downline tree (children only; no parent fields)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    partnerId: str = Field(validation_alias=AliasChoices("partnerId", "agentId"))
    name: str
    phone: str
    email: str = ""
    location: str = ""
    status: str = ""
    selfCommission: float = 0
    introducerCommission: float = Field(
        default=0,
        validation_alias=AliasChoices("introducerCommission", "commission"),
    )
    children: list[PartnerTeamMemberNode] = Field(default_factory=list)


class SetChildSelfCommissionRequest(BaseModel):
    """Parent partner sets direct child partner's selfCommission; introducerCommission is derived."""

    model_config = ConfigDict(extra="forbid")

    selfCommission: float = Field(
        ge=0,
        description="Child's commission % from investments; must be ≤ parent's selfCommission.",
    )


PartnerTeamMemberNode.model_rebuild()
