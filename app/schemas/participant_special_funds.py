from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AdminSpecialFundsAssign(BaseModel):
    """Assign special fund types to one or more participants (idempotent adds)."""

    model_config = ConfigDict(extra="forbid")

    participantIds: list[str] = Field(..., min_length=1, max_length=500)
    fundTypeIds: list[int] = Field(..., min_length=1, max_length=100)
    setIsEligible: bool = Field(
        default=True,
        description="If true, sets participants.isEligible = true for all listed participants.",
    )


class AdminSpecialFundsRemove(BaseModel):
    """Remove special fund assignments. Omit fundTypeIds to clear all special links for listed participants."""

    model_config = ConfigDict(extra="forbid")

    participantIds: list[str] = Field(..., min_length=1, max_length=500)
    fundTypeIds: Optional[list[int]] = Field(
        default=None,
        description="If null or empty, removes every participant_special_funds row for these participants.",
    )


class AdminSpecialFundsMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participantIds: list[str]
    fundTypeIdsAffected: list[int]
    linksUpserted: int = 0
    linksRemoved: int = 0


class ParticipantSpecialFundIdsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participantId: str
    isEligible: bool
    eligibleSpecialFundIds: list[int]
