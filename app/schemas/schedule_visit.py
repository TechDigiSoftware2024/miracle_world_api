from datetime import datetime
from typing import Any, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class ScheduleVisitCreate(BaseModel):
    visitorName: str
    alternatePhone: Optional[str] = None
    selectedDate: str
    visitTime: str
    userId: str
    propertyId: str
    propertyName: str


class ScheduleVisitResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    visitorName: str
    alternatePhone: Optional[str] = None
    selectedDate: str
    visitTime: str
    userId: str
    propertyId: str
    propertyName: str
    createdAt: datetime = Field(validation_alias=AliasChoices("createdAt", "created_at"))

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v: Any) -> Any:
        if v is None:
            return v
        return int(v)

    @field_validator(
        "visitorName",
        "selectedDate",
        "visitTime",
        "userId",
        "propertyId",
        "propertyName",
        mode="before",
    )
    @classmethod
    def coerce_str(cls, v: Any) -> Any:
        if v is None:
            return v
        return str(v)

    @field_validator("alternatePhone", mode="before")
    @classmethod
    def coerce_optional_str(cls, v: Any) -> Any:
        if v is None:
            return None
        return str(v)


class ScheduleVisitDeleteResponse(BaseModel):
    message: str
    id: int
