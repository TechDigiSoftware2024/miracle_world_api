from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class PendingPaymentsSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    participant_row_count: int = Field(alias="participantRowCount")
    partner_group_count: int = Field(alias="partnerGroupCount")
    total_row_count: int = Field(alias="totalRowCount")
    total_amount_participants: float = Field(alias="totalAmountParticipants")
    total_amount_partners: float = Field(alias="totalAmountPartners")
    grand_total: float = Field(alias="grandTotal")


class ParticipantPendingRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    row_type: Literal["participant"] = Field(alias="rowType", description="Discriminator for Flutter.")
    schedule_id: int = Field(alias="scheduleId")
    investment_id: str = Field(alias="investmentId")
    participant_id: str = Field(alias="participantId")
    participant_name: str = Field(alias="participantName")
    participant_phone: str = Field(default="", alias="participantPhone")
    month_number: int = Field(alias="monthNumber")
    amount: float
    payout_date: datetime = Field(alias="payoutDate")
    status: str
    payment_method: str = Field(default="BANK", alias="paymentMethod")
    fund_id: str = Field(default="", alias="fundId")
    fund_name: str = Field(default="", alias="fundName")


class PartnerCommissionPendingLineDetail(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    commission_schedule_id: int = Field(alias="commissionScheduleId")
    beneficiary_partner_id: str = Field(alias="beneficiaryPartnerId")
    investment_id: str = Field(alias="investmentId")
    participant_id: str = Field(alias="participantId")
    participant_name: str = Field(alias="participantName")
    month_number: int = Field(alias="monthNumber")
    amount: float
    payout_date: datetime = Field(alias="payoutDate")
    status: str
    level: int
    source_partner_id: str = Field(default="", alias="sourcePartnerId")


class PartnerGroupPendingRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    row_type: Literal["partner"] = Field(alias="rowType")
    group_key: str = Field(alias="groupKey")
    beneficiary_partner_id: str = Field(alias="beneficiaryPartnerId")
    beneficiary_name: str = Field(alias="beneficiaryName")
    beneficiary_phone: str = Field(default="", alias="beneficiaryPhone")
    total_amount: float = Field(alias="totalAmount")
    line_count: int = Field(alias="lineCount")
    investment_count: int = Field(alias="investmentCount")
    month_count: int = Field(alias="monthCount")
    month_label: str = Field(alias="monthLabel")
    earliest_payout_date: datetime = Field(alias="earliestPayoutDate")
    display_status: str = Field(alias="displayStatus")
    lines: List[PartnerCommissionPendingLineDetail]


class PendingPaymentsListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    summary: PendingPaymentsSummary
    rows: List[Union[ParticipantPendingRow, PartnerGroupPendingRow]]


class MarkPaidRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    participant_schedule_ids: List[int] = Field(default_factory=list, alias="participantScheduleIds")
    partner_commission_schedule_ids: List[int] = Field(
        default_factory=list,
        alias="partnerCommissionScheduleIds",
    )
    record_payouts: bool = Field(default=False, alias="recordPayouts")
    payment_method: Literal["BANK", "IMPS/NEFT", "CASH"] = Field(default="BANK", alias="paymentMethod")
    transaction_id: Optional[str] = Field(default=None, alias="transactionId")
    remarks: str = Field(default="")
    partner_payout_batch_key: Optional[str] = Field(
        default=None,
        alias="partnerPayoutBatchKey",
        description=(
            "Optional shared id (e.g. UUID) across several mark-paid calls: partner paid payouts for the same "
            "beneficiary merge into one row (amounts summed, commission line ids appended). "
            "Also merges when transactionId is set and matches an existing partner paid payout for that user."
        ),
    )


class MarkPaidItemResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ref: str = Field(description="scheduleId or comma-separated commission ids")
    kind: Literal["participant", "partner"]
    ok: bool
    detail: Optional[str] = None


class MarkPaidResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    results: List[MarkPaidItemResult]
    payouts_recorded: int = Field(default=0, alias="payoutsRecorded")


class GeneratePayoutsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    participant_schedule_ids: List[int] = Field(default_factory=list, alias="participantScheduleIds")
    partner_commission_schedule_ids: List[int] = Field(
        default_factory=list,
        alias="partnerCommissionScheduleIds",
    )
    payment_method: Literal["BANK", "IMPS/NEFT", "CASH"] = Field(default="BANK", alias="paymentMethod")
    remarks: str = Field(default="")
    partner_payout_batch_key: Optional[str] = Field(
        default=None,
        alias="partnerPayoutBatchKey",
        description="Same as mark-paid: merge pending partner payouts per beneficiary across calls with this key.",
    )



class GeneratePayoutsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    payouts_created: int = Field(alias="payoutsCreated")
    payout_ids: List[str] = Field(alias="payoutIds")
