from pydantic import BaseModel, Field, AliasChoices, ConfigDict, field_validator
from datetime import datetime
from typing import Optional, Any


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

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v: Any) -> Any:
        if v is None:
            return v
        return int(v)

    @field_validator("phone", "role", "name", "status", "introducerId", mode="before")
    @classmethod
    def coerce_str(cls, v: Any) -> Any:
        if v is None:
            return v
        return str(v)

    @field_validator("pin", "message", mode="before")
    @classmethod
    def coerce_optional_str(cls, v: Any) -> Any:
        if v is None:
            return None
        return str(v)


class TrackResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
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

    @field_validator("id", mode="before")
    @classmethod
    def coerce_track_id(cls, v: Any) -> Any:
        if v is None:
            return v
        return int(v)


class UserRequestDeleteResponse(BaseModel):
    message: str
    id: int
