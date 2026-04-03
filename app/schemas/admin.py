from pydantic import BaseModel
from datetime import datetime


class AdminResponse(BaseModel):
    id: int
    adminId: str
    name: str
    phone: str
    access_sections: str
    status: str
    createdAt: datetime
