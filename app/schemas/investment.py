import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


InvestmentStatus = Literal[
    "Processing",
    "Pending Approval",
    "Active",
    "Matured",
    "Completed",
]
PaymentLineStatus = Literal["paid", "due", "pending"]
ScheduleLineType = Literal["full", "prorata", "adjustment"]
PartnerCommissionLineStatus = Literal["paid", "due", "pending"]


class InvestmentParticipantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str = Field(default="", max_length=20)
    fundId: str = Field(default="", max_length=20)
    fundName: str = Field(default="", max_length=100)
    investedAmount: float = Field(ge=0)
    roiPercentage: float = Field(
        ge=0,
        description="Return on principal per month (not annual): monthly cash = principal × roi% ÷ 100.",
    )
    durationMonths: int = Field(ge=0)
    investmentDate: Optional[datetime] = None
    monthlyPayout: Optional[float] = Field(
        default=None,
        ge=0,
        description="If omitted and durationMonths > 0: investedAmount × (roiPercentage ÷ 100).",
    )
    isProfitCapitalPerMonth: bool = False

    @model_validator(mode="after")
    def default_monthly_payout(self):
        if self.monthlyPayout is not None:
            return self
        if self.durationMonths <= 0:
            self.monthlyPayout = 0.0
            return self
        self.monthlyPayout = round(
            self.investedAmount * (self.roiPercentage / 100.0),
            2,
        )
        return self


class InvestmentAdminCreate(InvestmentParticipantCreate):
    participantId: str = Field(min_length=1, max_length=32)
    status: InvestmentStatus = "Processing"


class InvestmentDocUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    investmentDoc: str = Field(min_length=1, max_length=4096)


class InvestmentAdminUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: Optional[str] = Field(default=None, max_length=20)
    fundId: Optional[str] = Field(default=None, max_length=20)
    fundName: Optional[str] = Field(default=None, max_length=100)
    investedAmount: Optional[float] = Field(default=None, ge=0)
    roiPercentage: Optional[float] = Field(
        default=None,
        ge=0,
        description="Per month on principal (same meaning as on create).",
    )
    durationMonths: Optional[int] = Field(default=None, ge=0)
    investmentDate: Optional[datetime] = None
    monthlyPayout: Optional[float] = Field(default=None, ge=0)
    isProfitCapitalPerMonth: Optional[bool] = None


class InvestmentStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: InvestmentStatus
    investmentStartDate: Optional[datetime] = Field(
        default=None,
        description="When moving to Active: anchor date for schedule (defaults to now UTC).",
    )


class InvestmentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    investmentId: str = Field(
        validation_alias=AliasChoices("investmentId", "investment_id")
    )
    participantId: str = Field(
        validation_alias=AliasChoices("participantId", "participant_id")
    )
    agentId: str = Field(default="", validation_alias=AliasChoices("agentId", "agent_id"))
    fundId: str = Field(default="", validation_alias=AliasChoices("fundId", "fund_id"))
    fundName: str = Field(default="", validation_alias=AliasChoices("fundName", "fund_name"))
    investedAmount: float
    roiPercentage: float = Field(
        validation_alias=AliasChoices("roiPercentage", "roi_percentage"),
        description="% of invested principal paid per month (not annual).",
    )
    durationMonths: int = Field(
        validation_alias=AliasChoices("durationMonths", "duration_months")
    )
    investmentDate: datetime = Field(
        validation_alias=AliasChoices("investmentDate", "investment_date")
    )
    nextPayoutDate: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("nextPayoutDate", "next_payout_date")
    )
    monthlyPayout: float = Field(
        validation_alias=AliasChoices("monthlyPayout", "monthly_payout"),
        description="Nominal monthly installment before pro-rata / adjustment on schedule lines.",
    )
    isProfitCapitalPerMonth: bool = Field(
        validation_alias=AliasChoices("isProfitCapitalPerMonth", "is_profit_capital_per_month")
    )
    status: InvestmentStatus
    investmentStartDate: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("investmentStartDate", "investment_start_date"),
    )
    investmentDoc: str = Field(
        default="", validation_alias=AliasChoices("investmentDoc", "investment_doc")
    )
    createdAt: datetime = Field(validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("updatedAt", "updated_at")
    )


class PaymentScheduleResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: int = Field(description="Database row id: integer 1, 2, 3, … (no prefix).")
    investmentId: str = Field(
        validation_alias=AliasChoices("investmentId", "investment_id")
    )
    monthNumber: int = Field(
        validation_alias=AliasChoices("monthNumber", "month_number"),
        description="Installment index for this investment, starting at 1 (no prefix).",
    )
    payoutDate: datetime = Field(
        validation_alias=AliasChoices("payoutDate", "payout_date")
    )
    amount: float
    lineType: ScheduleLineType = Field(
        default="full",
        validation_alias=AliasChoices("lineType", "line_type"),
        description="full = standard month; prorata = first partial month; adjustment = closing balance line.",
    )
    isProrata: bool = Field(
        default=False,
        validation_alias=AliasChoices("isProrata", "is_prorata"),
    )
    daysCount: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("daysCount", "days_count"),
        description="Calendar days in the pro-rata slice (first line only).",
    )
    perDayAmount: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices("perDayAmount", "per_day_amount"),
        description="Monthly amount ÷ days in start month, 2 dp (first line only).",
    )
    status: PaymentLineStatus
    createdAt: datetime = Field(validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("updatedAt", "updated_at")
    )


class PaymentScheduleStatusPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PaymentLineStatus


class PartnerCommissionScheduleResponse(BaseModel):
    """One monthly commission accrual line for a beneficiary partner on an investment."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: int
    investmentId: str = Field(
        validation_alias=AliasChoices("investmentId", "investment_id"),
    )
    monthNumber: int = Field(
        validation_alias=AliasChoices("monthNumber", "month_number"),
    )
    payoutDate: datetime = Field(
        validation_alias=AliasChoices("payoutDate", "payout_date"),
    )
    beneficiaryPartnerId: str = Field(
        validation_alias=AliasChoices("beneficiaryPartnerId", "beneficiary_partner_id"),
    )
    sourcePartnerId: str = Field(
        default="",
        validation_alias=AliasChoices("sourcePartnerId", "source_partner_id"),
    )
    level: int = Field(description="0 = direct agent on deal; 1+ = uplines.")
    ratePercent: float = Field(
        validation_alias=AliasChoices("ratePercent", "rate_percent"),
        description="Snapshot % of invested principal for this line (monthly).",
    )
    amount: float
    status: PartnerCommissionLineStatus
    createdAt: datetime = Field(validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("updatedAt", "updated_at"),
    )


class AdminInvestmentFundStatsItem(BaseModel):
    """Per fund type: how much capital, how many investment rows, how many users (partners optional)."""

    model_config = ConfigDict(extra="forbid")

    fundId: Optional[int] = Field(
        default=None,
        description="`fund_types.id` when `investments.fundId` is numeric; null for unspecified/non-numeric.",
    )
    fundName: str = Field(
        default="",
        description="Name from `fund_types` (or a fallback).",
    )
    totalInvestedAmount: float
    investmentCount: int
    userInvestorCount: int = Field(
        description="Distinct participants (users) with at least one investment in this fund.",
    )
    partnerCount: int = Field(
        default=0,
        description="Distinct non-empty `agentId` (partners) on investments in this fund.",
    )


class AdminInvestmentStatsResponse(BaseModel):
    """
    **Admin overview** (not investment-only scope):

    * **Portfolio** — total principal through investments and total investment row count.
    * **App** — total participant and partner user rows; pending signup **user_requests** (`status` = `pending`).
    * **funds** — each fund type with amounts, investment counts, and how many **users** invested in that fund.
    """

    model_config = ConfigDict(extra="forbid")

    totalInvestedAmount: float = Field(
        description="Sum of `investedAmount` across all investment rows (capital through investments).",
    )
    totalInvestmentCount: int = Field(
        description="Total number of investment rows in the system.",
    )
    totalParticipantsInApp: int = Field(
        description="Count of rows in the **participants** table.",
    )
    totalPartnersInApp: int = Field(
        description="Count of rows in the **partners** table.",
    )
    pendingUserRequestsCount: int = Field(
        description="**user_requests** with `status` = `pending` (join approvals).",
    )
    funds: list[AdminInvestmentFundStatsItem] = Field(
        default_factory=list,
        description="Per `fund_type`: amounts, investment counts, and user-investor counts. Optional `fund_type_id` filter narrows this list only.",
    )
