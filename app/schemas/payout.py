from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PayoutStatus = Literal["pending", "processing", "paid", "failed", "cancelled"]
PayoutMethod = Literal["BANK", "IMPS/NEFT", "CASH"]
PayoutType = Literal["commission", "monthly_income", "extra_income"]
RecipientType = Literal["participant", "partner"]
CreatedBy = Literal["admin", "automatic"]


class PayoutResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    payoutId: str
    userId: str
    recipientType: RecipientType
    amount: float
    status: PayoutStatus
    paymentMethod: PayoutMethod
    transactionId: Optional[str] = None
    investmentId: Optional[str] = None
    payoutDate: datetime
    remarks: str
    payoutType: PayoutType
    createdBy: CreatedBy
    createdByAdminId: Optional[str] = None
    levelDepth: Optional[int] = Field(
        default=None,
        description="MLM downline level for partner payouts (1 = direct, 2+ = deeper). Null for participants.",
    )
    createdAt: datetime
    updatedAt: Optional[datetime] = None


class PayoutAdminCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    userId: str = Field(min_length=1, max_length=64)
    recipientType: RecipientType
    amount: float = Field(gt=0)
    status: PayoutStatus = "pending"
    paymentMethod: PayoutMethod
    transactionId: Optional[str] = Field(default=None, max_length=256)
    investmentId: Optional[str] = Field(default=None, max_length=32)
    payoutDate: datetime
    remarks: str = Field(default="", max_length=4096)
    payoutType: PayoutType
    createdBy: CreatedBy = "admin"
    levelDepth: Optional[int] = Field(
        default=None,
        ge=1,
        le=100,
        description="MLM level for partner payouts only; omit for participants.",
    )

    @model_validator(mode="after")
    def level_depth_for_partner_only(self):
        if self.recipientType == "participant" and self.levelDepth is not None:
            raise ValueError("levelDepth must be omitted for participant payouts (MLM level applies to partners only)")
        return self


class PayoutAdminUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Optional[float] = Field(default=None, gt=0)
    status: Optional[PayoutStatus] = None
    paymentMethod: Optional[PayoutMethod] = None
    transactionId: Optional[str] = Field(default=None, max_length=256)
    investmentId: Optional[str] = Field(default=None, max_length=32)
    payoutDate: Optional[datetime] = None
    remarks: Optional[str] = Field(default=None, max_length=4096)
    payoutType: Optional[PayoutType] = None
    userId: Optional[str] = Field(default=None, min_length=1, max_length=64)
    recipientType: Optional[RecipientType] = None
    levelDepth: Optional[int] = Field(default=None, ge=1, le=100)

    @field_validator("transactionId", "remarks", "investmentId", mode="before")
    @classmethod
    def empty_str_to_unset(cls, v):
        if v == "":
            return None
        return v

    @model_validator(mode="after")
    def level_depth_consistency(self):
        rt = self.recipientType
        ld = self.levelDepth
        if rt == "participant" and ld is not None:
            raise ValueError("levelDepth cannot be set when recipientType is participant")
        return self
