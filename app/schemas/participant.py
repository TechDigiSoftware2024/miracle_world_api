from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class ParticipantResponse(BaseModel):
    id: int
    investorId: str
    name: str
    phone: str
    email: str
    address: str
    introducer: str
    profileImage: Optional[str] = None
    status: str
    totalInvestment: float
    offeredValues: Optional[str] = None
    lastVisit: Optional[datetime] = None
    lastUpdated: Optional[datetime] = None
    createdAt: datetime
