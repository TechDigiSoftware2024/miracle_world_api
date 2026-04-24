from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


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
    selfProfit: float = 0
    generatedProfitByTeam: float = 0
    totalDeals: int = 0
    totalTeamMembers: int = 0
    createdAt: datetime
    portfolioAmount: float = Field(
        default=0,
        description="Book view: downline principal counted in participantInvestedTotal plus unpaid schedule lines (pending/due).",
    )
    paidAmount: float = Field(default=0, description="Total paid partner payouts (all types).")
    pendingAmount: float = Field(
        default=0,
        description="Partner payouts in pending or processing status.",
    )
    perMonthPendingAmount: float = Field(
        default=0,
        description="Sum of pending/due schedule lines on downline investments with payoutDate in the current UTC month.",
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
        description="Paid partner payouts with levelDepth null or ≤1 (direct / self).",
    )
    teamEarningAmount: float = Field(
        default=0,
        description="Paid partner payouts with levelDepth ≥2 (team / downline).",
    )
    portfolioUpdatedAt: Optional[datetime] = None

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
            ("perMonthPendingAmount", 0),
            ("participantInvestedTotal", 0),
            ("introducerCommissionAmount", 0),
            ("selfEarningAmount", 0),
            ("teamEarningAmount", 0),
            ("selfCommission", 0),
            ("selfProfit", 0),
            ("generatedProfitByTeam", 0),
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
    selfProfit: Optional[float] = None
    generatedProfitByTeam: Optional[float] = None
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
