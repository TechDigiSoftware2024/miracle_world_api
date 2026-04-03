from pydantic import BaseModel
from datetime import datetime


class PartnerResponse(BaseModel):
    id: int
    agentId: str
    name: str
    phone: str
    email: str
    location: str
    introducer: str
    profileImage: str
    status: str
    commission: float
    selfCommission: float
    selfProfit: float
    generatedProfitByTeam: float
    totalDeals: int
    totalTeamMembers: int
    createdAt: datetime
