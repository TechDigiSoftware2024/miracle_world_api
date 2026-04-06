import json
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

PropertyType = Literal["residential", "commercial", "land"]
PropertyPurpose = Literal["rent", "buy", "sell"]
PropertyStatus = Literal["available", "sold", "pending"]

MAX_IMAGES = 40
MAX_IMAGE_URL_LEN = 2048


def _validate_images(v: list[str]) -> list[str]:
    if len(v) > MAX_IMAGES:
        raise ValueError(f"At most {MAX_IMAGES} images allowed")
    for i, url in enumerate(v):
        s = url.strip()
        if len(s) > MAX_IMAGE_URL_LEN:
            raise ValueError(f"Image URL {i + 1} is too long")
        if not s:
            raise ValueError("Image URLs cannot be empty")
    return [u.strip() for u in v]


class PropertyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=20000)
    type: PropertyType
    purpose: PropertyPurpose
    price: float = Field(ge=0)
    area: float = Field(ge=0, description="Area in sqft")
    address: str = Field(default="", max_length=500)
    city: str = Field(default="", max_length=200)
    state: str = Field(default="", max_length=200)
    zipCode: str = Field(default="", max_length=20)
    images: list[str] = Field(default_factory=list)
    status: PropertyStatus = "available"
    amenities: Optional[dict[str, Any]] = None

    @field_validator("images", mode="before")
    @classmethod
    def coerce_images(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v]
        raise ValueError("images must be a list of URL strings")

    @field_validator("images")
    @classmethod
    def validate_images_list(cls, v: list[str]) -> list[str]:
        return _validate_images(v)


class PropertyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    description: Optional[str] = Field(default=None, max_length=20000)
    type: Optional[PropertyType] = None
    purpose: Optional[PropertyPurpose] = None
    price: Optional[float] = Field(default=None, ge=0)
    area: Optional[float] = Field(default=None, ge=0)
    address: Optional[str] = Field(default=None, max_length=500)
    city: Optional[str] = Field(default=None, max_length=200)
    state: Optional[str] = Field(default=None, max_length=200)
    zipCode: Optional[str] = Field(default=None, max_length=20)
    images: Optional[list[str]] = None
    status: Optional[PropertyStatus] = None
    amenities: Optional[dict[str, Any]] = None

    @field_validator("images", mode="before")
    @classmethod
    def coerce_images(cls, v: Any) -> Optional[list[str]]:
        if v is None:
            return None
        if isinstance(v, list):
            return [str(x) for x in v]
        raise ValueError("images must be a list of URL strings")

    @field_validator("images")
    @classmethod
    def validate_images_list(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return None
        return _validate_images(v)


class PropertyResponse(BaseModel):
    """Matches Flutter: String id, propertyId (same numeric id), camelCase fields."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    propertyId: int
    title: str
    description: str
    type: str
    purpose: str
    price: float
    area: float
    address: str
    city: str
    state: str
    zipCode: str = Field(validation_alias=AliasChoices("zipCode", "zip_code"))
    images: list[str] = Field(default_factory=list)
    status: str
    amenities: Optional[dict[str, Any]] = None
    createdAt: datetime = Field(
        validation_alias=AliasChoices("createdAt", "created_at")
    )
    updatedAt: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("updatedAt", "updated_at"),
    )

    @model_validator(mode="before")
    @classmethod
    def from_db(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        pk = d.get("id")
        if pk is not None:
            i = int(pk)
            d["id"] = str(i)
            d["propertyId"] = i
        imgs = d.get("images")
        if imgs is None:
            d["images"] = []
        elif isinstance(imgs, str):
            try:
                parsed = json.loads(imgs)
                d["images"] = parsed if isinstance(parsed, list) else []
            except Exception:
                d["images"] = []
        elif not isinstance(imgs, list):
            d["images"] = []
        else:
            d["images"] = [str(x) for x in imgs]
        am = d.get("amenities")
        if am is not None and not isinstance(am, dict):
            d["amenities"] = None
        if "zipCode" not in d and "zip_code" in d:
            d["zipCode"] = d["zip_code"]
        return d
