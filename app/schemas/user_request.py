from pydantic import BaseModel, Field, AliasChoices, ConfigDict
from datetime import datetime
from typing import Optional


class RequestCreate(BaseModel):
    phone: str
    role: str
    name: str
    introducerId: str


class RequestResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    phone: str
    role: str
    name: str
    introducerId: str = Field(validation_alias=AliasChoices("introducerId", "introducer_id"))
    status: str
    message: Optional[str] = None
    pin: Optional[str] = None
    createdAt: datetime = Field(validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("updatedAt", "updated_at"),
    )


class TrackResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    phone: str
    role: str
    status: str
    message: Optional[str] = None
    createdAt: datetime = Field(validation_alias=AliasChoices("createdAt", "created_at"))
    updatedAt: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("updatedAt", "updated_at"),
    )
