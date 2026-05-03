from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from datetime import datetime


class AdminResponse(BaseModel):
    adminId: str
    name: str
    phone: str
    access_sections: str
    status: str
    createdAt: datetime


class AdminPartnerFinancialSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    partnerId: str = Field(validation_alias=AliasChoices("partnerId", "agentId"))
    name: str
    portfolioAmount: float = 0.0
    totalBusiness: float = 0.0
    participantInvestedTotal: float = 0.0
    paidAmount: float = 0.0
    pendingAmount: float = 0.0
    selfEarningAmount: float = 0.0
    teamEarningAmount: float = 0.0
