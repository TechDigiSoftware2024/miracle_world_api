from fastapi import APIRouter, HTTPException, status

from app.schemas.app_settings import AppSettingsResponse
from app.utils.app_settings_repo import fetch_app_settings_row

router = APIRouter(tags=["Public"])


@router.get("/settings", response_model=AppSettingsResponse)
def get_public_app_settings():
    """Public: company info and default introducer IDs for signup / UI."""
    row = fetch_app_settings_row()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App settings are not configured. Run SQL for app_settings and seed, or ask an admin.",
        )
    return AppSettingsResponse.model_validate(row)
