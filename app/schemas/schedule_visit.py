from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ScheduleVisitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visitorName: str
    alternatePhone: Optional[str] = None
    selectedDate: str
    visitTime: str
    userId: Optional[str] = None
    propertyId: str
    propertyName: str


class ScheduleVisitResponse(BaseModel):
    id: int
    visitorName: str
    alternatePhone: Optional[str] = None
    selectedDate: str
    visitTime: str
    userId: str
    propertyId: str
    propertyName: str
    createdAt: datetime
