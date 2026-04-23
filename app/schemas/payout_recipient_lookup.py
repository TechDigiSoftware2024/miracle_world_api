from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class PayoutRecipientParticipantItem(BaseModel):
    """Minimal participant row for admin payout / recipient pickers."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    participantId: str = Field(validation_alias=AliasChoices("participantId", "investorId"))
    name: str
    phone: str
    status: str


class PayoutRecipientPartnerItem(BaseModel):
    """Minimal partner row for admin payout / recipient pickers."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    partnerId: str = Field(validation_alias=AliasChoices("partnerId", "agentId"))
    name: str
    phone: str
    status: str
