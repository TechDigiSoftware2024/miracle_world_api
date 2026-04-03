from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class RequestCreate(BaseModel):
    phone: str
    role: str
    name: str
    introducerId: str


class RequestResponse(BaseModel):
    id: int
    phone: str
    role: str
    name: str
    introducerId: str
    status: str
    message: Optional[str] = None
    pin: Optional[str] = None
    createdAt: datetime
    updatedAt: Optional[datetime] = None


class TrackResponse(BaseModel):
    name: str
    phone: str
    role: str
    status: str
    message: Optional[str] = None
    createdAt: datetime
    updatedAt: Optional[datetime] = None
