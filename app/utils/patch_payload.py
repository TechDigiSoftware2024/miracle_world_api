from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel


def dump_update_or_400(model: BaseModel) -> dict[str, Any]:
    data = model.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    return data
