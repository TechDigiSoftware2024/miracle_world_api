from typing import Any, Optional

from app.db.database import supabase


def fetch_app_settings_row() -> Optional[dict[str, Any]]:
    result = supabase.table("app_settings").select("*").eq("id", 1).limit(1).execute()
    return result.data[0] if result.data else None
