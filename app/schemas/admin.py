from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from datetime import datetime


class AdminResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    adminId: str
    name: str
    phone: str
    access_sections: str
    role: str = "super_admin"
    status: str
    createdAt: datetime
    createdByAdminId: Optional[str] = None


class AdminUserCreateRequest(BaseModel):
    name: str
    phone: str
    mpin: str
    role: str = "sub_admin"
    access_sections: str = ""
    status: str = "active"


class AdminUserPatchRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    mpin: Optional[str] = None
    role: Optional[str] = None
    access_sections: Optional[str] = None
    status: Optional[str] = None


class AdminUserAccessPatchRequest(BaseModel):
    access_sections: str


class AdminUserStatusPatchRequest(BaseModel):
    status: str


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
