from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class BankDetailsExportBlock(BaseModel):
    """Subset of bank_details for Excel/export."""

    model_config = ConfigDict(populate_by_name=True)

    holder_name: str = Field(default="", alias="holderName")
    bank_name: str = Field(default="", alias="bankName")
    account_number: str = Field(default="", alias="accountNumber")
    ifsc_code: str = Field(default="", alias="ifscCode")
    upi_id: str = Field(default="", alias="upiId")
    branch_name: str = Field(default="", alias="branchName")
    account_type: str = Field(default="", alias="accountType")
    status: str = ""


class ClosingPayoutRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    payout_id: str = Field(alias="payoutId")
    user_id: str = Field(alias="userId")
    recipient_type: str = Field(alias="recipientType")
    display_name: str = Field(alias="displayName")
    phone: str = ""
    email_or_contact: str = Field(default="", alias="emailOrContact")
    amount: float
    payout_date: datetime = Field(alias="payoutDate")
    status: str
    payment_method: str = Field(alias="paymentMethod")
    transaction_id: Optional[str] = Field(default=None, alias="transactionId")
    payout_type: str = Field(alias="payoutType")
    investment_id: Optional[str] = Field(default=None, alias="investmentId")
    remarks: str = ""
    bank_details: Optional[BankDetailsExportBlock] = Field(default=None, alias="bankDetails")


class ClosingPayoutSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    payout_count: int = Field(alias="payoutCount")
    unique_users: int = Field(alias="uniqueUsers")
    total_amount: float = Field(alias="totalAmount")
    amount_participants: float = Field(alias="amountParticipants")
    amount_partners: float = Field(alias="amountPartners")


class ClosingPayoutReportResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    summary: ClosingPayoutSummary
    rows: List[ClosingPayoutRow]


class ClosingInvestmentsExportResponse(BaseModel):
    """Monthly closing pack: investment rows for Excel (4 logical sheets + hierarchy views)."""

    model_config = ConfigDict(populate_by_name=True)

    closing_year: int = Field(alias="closingYear")
    closing_month: int = Field(alias="closingMonth")
    investment_statuses: List[str] = Field(alias="investmentStatuses")
    tds_rate_percent: float = Field(alias="tdsRatePercent")
    full_hierarchy: List[dict[str, Any]] = Field(alias="fullHierarchy", description="Participant × partner rows")
    by_investment: List[dict[str, Any]] = Field(alias="byInvestment", description="One row per investment")
    by_partner: List[dict[str, Any]] = Field(alias="byPartner", description="Partner × investment rows")
    monthly_participants: List[dict[str, Any]] = Field(
        alias="monthlyParticipants",
        description="Sheet 1 style: payout-in-month + partner comm this month",
    )
    monthly_participant_summary: List[dict[str, Any]] = Field(
        alias="monthlyParticipantSummary",
        description="Sheet 2 style: participant rollup + TDS",
    )
    monthly_agent_commissions: List[dict[str, Any]] = Field(
        alias="monthlyAgentCommissions",
        description="Sheet 3 style: one row per commission schedule line in month",
    )
    monthly_agent_summary: List[dict[str, Any]] = Field(
        alias="monthlyAgentSummary",
        description="Sheet 4 style: partner rollup + TDS",
    )
