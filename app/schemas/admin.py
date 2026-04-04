from pydantic import BaseModel
from datetime import datetime


class AdminResponse(BaseModel):
    adminId: str
    name: str
    phone: str
    access_sections: str
    status: str
    createdAt: datetime
