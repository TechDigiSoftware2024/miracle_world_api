import json
from datetime import datetime
from typing import Any, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_DESCRIPTION_POINTS = 80
MAX_DESCRIPTION_POINT_LEN = 2000


def _validate_description_points(v: list[str]) -> list[str]:
    if len(v) > MAX_DESCRIPTION_POINTS:
        raise ValueError(f"At most {MAX_DESCRIPTION_POINTS} description points allowed")
    out = []
    for i, line in enumerate(v):
        s = line.strip()
        if len(s) > MAX_DESCRIPTION_POINT_LEN:
            raise ValueError(
                f"Description point {i + 1} exceeds {MAX_DESCRIPTION_POINT_LEN} characters"
            )
        out.append(s)
    return out


class FundTypeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fundName: str = Field(min_length=1, max_length=300)
    minimumInvestmentAmount: float = Field(ge=0, default=0)
    maximumInvestmentAmount: float = Field(ge=0, default=0)
    isMaxInvestmentUnlimited: bool = False
    isROIFixed: bool = False
    fixedROI: Optional[float] = None
    minimumROI: Optional[float] = None
    maximumROI: Optional[float] = None
    status: str = Field(default="active", max_length=50)
    durationType: str = Field(default="", max_length=100)
    duration: Optional[int] = Field(
        default=None,
        ge=0,
        description="Total duration in months only (not years).",
    )
    notes: str = Field(default="", max_length=10000)
    description: list[str] = Field(
        default_factory=list,
        description="Multiple bullet points shown to users (stored as JSON array).",
    )
    isProfitCapitalPerMonth: bool = Field(
        default=False,
        description="True if this fund pays profit plus capital per month.",
    )
    isSpecial: bool = Field(
        default=False,
        description="Marks the fund as special (e.g. featured or restricted).",
    )

    @field_validator("description", mode="before")
    @classmethod
    def coerce_description(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            if not v.strip():
                return []
            return [v.strip()]
        if isinstance(v, list):
            return [str(x) for x in v]
        raise ValueError("description must be a list of strings or a single string")

    @field_validator("description")
    @classmethod
    def validate_points(cls, v: list[str]) -> list[str]:
        return _validate_description_points(v)


class FundTypeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fundName: Optional[str] = Field(default=None, min_length=1, max_length=300)
    minimumInvestmentAmount: Optional[float] = Field(default=None, ge=0)
    maximumInvestmentAmount: Optional[float] = Field(default=None, ge=0)
    isMaxInvestmentUnlimited: Optional[bool] = None
    isROIFixed: Optional[bool] = None
    fixedROI: Optional[float] = None
    minimumROI: Optional[float] = None
    maximumROI: Optional[float] = None
    status: Optional[str] = Field(default=None, max_length=50)
    durationType: Optional[str] = Field(default=None, max_length=100)
    duration: Optional[int] = Field(
        default=None,
        ge=0,
        description="Total duration in months only (not years).",
    )
    notes: Optional[str] = Field(default=None, max_length=10000)
    description: Optional[list[str]] = None
    isProfitCapitalPerMonth: Optional[bool] = None
    isSpecial: Optional[bool] = None

    @field_validator("description", mode="before")
    @classmethod
    def coerce_description(cls, v: Any) -> Optional[list[str]]:
        if v is None:
            return None
        if isinstance(v, str):
            if not v.strip():
                return []
            return [v.strip()]
        if isinstance(v, list):
            return [str(x) for x in v]
        raise ValueError("description must be a list of strings or a single string")

    @field_validator("description")
    @classmethod
    def validate_points(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return None
        return _validate_description_points(v)


class FundTypeResponse(BaseModel):
    """Shape aligned with Flutter `toMap` keys (fundId, dateCreated, description as list)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    fundId: int
    fundName: str = Field(validation_alias=AliasChoices("fundName", "fund_name"))
    minimumInvestmentAmount: float = Field(
        validation_alias=AliasChoices(
            "minimumInvestmentAmount", "minimum_investment_amount"
        )
    )
    maximumInvestmentAmount: float = Field(
        validation_alias=AliasChoices(
            "maximumInvestmentAmount", "maximum_investment_amount"
        )
    )
    isMaxInvestmentUnlimited: bool = Field(
        validation_alias=AliasChoices(
            "isMaxInvestmentUnlimited", "is_max_investment_unlimited"
        )
    )
    isROIFixed: bool = Field(validation_alias=AliasChoices("isROIFixed", "is_roi_fixed"))
    fixedROI: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("fixedROI", "fixed_roi")
    )
    minimumROI: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("minimumROI", "minimum_roi")
    )
    maximumROI: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("maximumROI", "maximum_roi")
    )
    status: str
    dateCreated: datetime = Field(
        validation_alias=AliasChoices("dateCreated", "createdAt", "created_at")
    )
    durationType: str = Field(
        default="", validation_alias=AliasChoices("durationType", "duration_type")
    )
    duration: Optional[int] = Field(
        default=None,
        description="Total duration in months only.",
    )
    notes: str = ""
    description: list[str] = Field(default_factory=list)
    updatedAt: Optional[datetime] = Field(
        default=None, validation_alias=AliasChoices("updatedAt", "updated_at")
    )
    isProfitCapitalPerMonth: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "isProfitCapitalPerMonth", "is_profit_capital_per_month"
        ),
        description="Profit plus capital paid per month.",
    )
    isSpecial: bool = Field(
        default=False,
        validation_alias=AliasChoices("isSpecial", "is_special"),
    )

    @model_validator(mode="before")
    @classmethod
    def map_db_row(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if "fundId" not in out and "id" in out:
            out["fundId"] = int(out["id"])
        if "dateCreated" not in out:
            if "createdAt" in out:
                out["dateCreated"] = out["createdAt"]
            elif "created_at" in out:
                out["dateCreated"] = out["created_at"]
        desc = out.get("description")
        if desc is None:
            out["description"] = []
        elif isinstance(desc, str):
            try:
                parsed = json.loads(desc)
                out["description"] = parsed if isinstance(parsed, list) else [str(parsed)]
            except Exception:
                out["description"] = [desc] if desc.strip() else []
        elif not isinstance(desc, list):
            out["description"] = []
        else:
            out["description"] = [str(x) for x in desc]
        if out.get("duration") is None and (
            out.get("durationMonths") is not None or out.get("durationYears") is not None
        ):
            m = out.get("durationMonths") or out.get("duration_months")
            y = out.get("durationYears") or out.get("duration_years")
            if m is None and y is None:
                out["duration"] = None
            else:
                out["duration"] = int(m or 0) + int(y or 0) * 12
        if out.get("isProfitCapitalPerMonth") is None:
            out["isProfitCapitalPerMonth"] = False
        if out.get("isSpecial") is None:
            out["isSpecial"] = False
        return out
