import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


InvestmentStatus = Literal["Active", "Pending Approval", "Processing", "Completed"]
PaymentLineStatus = Literal["paid", "due", "pending"]


class InvestmentParticipantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str = Field(default="", max_length=20)
    fundId: str = Field(default="", max_length=20)
    fundName: str = Field(default="", max_length=100)
    investedAmount: float = Field(ge=0)
    roiPercentage: float = Field(ge=0)
    durationMonths: int = Field(ge=0)
    investmentDate: Optional[datetime] = None
    monthlyPayout: Optional[float] = Field(
        default=None,
        ge=0,
        description="If omitted: investedAmount × roi% ÷ 12 when durationMonths > 0.",
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
            self.investedAmount * (self.roiPercentage / 100.0) / 12.0,
            2,
        )
        return self


class InvestmentAdminCreate(InvestmentParticipantCreate):
    participantId: str = Field(min_length=1, max_length=32)
    status: InvestmentStatus = "Pending Approval"


class InvestmentDocUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    investmentDoc: str = Field(min_length=1, max_length=4096)


class InvestmentAdminUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: Optional[str] = Field(default=None, max_length=20)
    fundId: Optional[str] = Field(default=None, max_length=20)
    fundName: Optional[str] = Field(default=None, max_length=100)
    investedAmount: Optional[float] = Field(default=None, ge=0)
    roiPercentage: Optional[float] = Field(default=None, ge=0)
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
        validation_alias=AliasChoices("roiPercentage", "roi_percentage")
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
        validation_alias=AliasChoices("monthlyPayout", "monthly_payout")
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
    status: PaymentLineStatus
    createdAt: datetime = Field(validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("updatedAt", "updated_at")
    )


class PaymentScheduleStatusPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PaymentLineStatus
