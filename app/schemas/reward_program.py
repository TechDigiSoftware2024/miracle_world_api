import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


ProgramType = Literal["MONTHLY", "ULTIMATE"]
BusinessType = Literal["DIRECT", "TEAM"]
GoalAmountUnit = Literal["LAKH", "CRORE"]


class RewardProgramCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    achieverTitle: str = Field(default="", max_length=500)
    programType: ProgramType
    businessType: Optional[BusinessType] = None
    goalAmountValue: float = Field(ge=0, default=0)
    goalAmountUnit: GoalAmountUnit = "LAKH"
    startDate: datetime
    goalDays: int = Field(ge=0)
    activationDaysAfterGoal: Optional[int] = Field(default=None, ge=0)


class RewardProgramUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    achieverTitle: Optional[str] = Field(default=None, max_length=500)
    programType: Optional[ProgramType] = None
    businessType: Optional[BusinessType] = None
    goalAmountValue: Optional[float] = Field(default=None, ge=0)
    goalAmountUnit: Optional[GoalAmountUnit] = None
    startDate: Optional[datetime] = None
    goalDays: Optional[int] = Field(default=None, ge=0)
    activationDaysAfterGoal: Optional[int] = Field(default=None, ge=0)
    isActive: Optional[bool] = None


class RewardProgramResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: int
    title: str
    achieverTitle: str = Field(
        default="", validation_alias=AliasChoices("achieverTitle", "achiever_title")
    )
    programType: ProgramType = Field(
        validation_alias=AliasChoices("programType", "program_type")
    )
    businessType: Optional[BusinessType] = Field(
        default=None, validation_alias=AliasChoices("businessType", "business_type")
    )
    goalAmountValue: float = Field(
        validation_alias=AliasChoices("goalAmountValue", "goal_amount_value")
    )
    goalAmountUnit: GoalAmountUnit = Field(
        validation_alias=AliasChoices("goalAmountUnit", "goal_amount_unit")
    )
    startDate: datetime = Field(validation_alias=AliasChoices("startDate", "start_date"))
    goalDays: int = Field(validation_alias=AliasChoices("goalDays", "goal_days"))
    endDate: datetime = Field(validation_alias=AliasChoices("endDate", "end_date"))
    activationDaysAfterGoal: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("activationDaysAfterGoal", "activation_days_after_goal"),
    )
    isActive: bool = Field(validation_alias=AliasChoices("isActive", "is_active"))
    createdAt: datetime = Field(validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("updatedAt", "updated_at")
    )


class RewardOfferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Optional[str] = Field(
        default=None,
        max_length=80,
        description="Optional stable id; a UUID is generated if omitted.",
    )
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=20000)
    imageUrl: str = Field(default="", max_length=4096)

    @field_validator("id", mode="before")
    @classmethod
    def empty_id_to_none(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return str(v).strip()


class RewardOfferAdminCreate(RewardOfferCreate):
    """Admin create: includes which program this offer belongs to."""

    programId: int = Field(validation_alias=AliasChoices("programId", "program_id"))


class RewardOfferUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    description: Optional[str] = Field(default=None, max_length=20000)
    imageUrl: Optional[str] = Field(default=None, max_length=4096)


class RewardOfferResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    programId: int = Field(validation_alias=AliasChoices("programId", "program_id"))
    title: str
    description: str = ""
    imageUrl: str = Field(default="", validation_alias=AliasChoices("imageUrl", "image_url"))
    createdAt: datetime = Field(validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("updatedAt", "updated_at")
    )


class RewardProgramWithOffersResponse(RewardProgramResponse):
    offers: list[RewardOfferResponse] = Field(default_factory=list)
