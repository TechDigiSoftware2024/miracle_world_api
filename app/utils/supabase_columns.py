"""Map Supabase/PostgREST column names: camelCase (quoted SQL) vs snake_case (default UI)."""

from typing import Optional


def user_request_row_style(row: dict) -> str:
    camel_v = row.get("introducerId")
    snake_v = row.get("introducer_id")
    if camel_v not in (None, ""):
        return "camel"
    if snake_v not in (None, ""):
        return "snake"
    if "introducerId" in row:
        return "camel"
    if "introducer_id" in row:
        return "snake"
    return "camel"


def approve_keys(style: str) -> dict:
    if style == "snake":
        return {
            "p_investor": "investor_id",
            "p_phone": "phone",
            "p_name": "name",
            "p_email": "email",
            "p_address": "address",
            "p_introducer": "introducer",
            "p_mpin": "mpin",
            "p_status": "status",
            "p_total": "total_investment",
            "a_agent": "agent_id",
            "a_phone": "phone",
            "a_name": "name",
            "a_email": "email",
            "a_location": "location",
            "a_introducer": "introducer",
            "a_mpin": "mpin",
            "a_profile": "profile_image",
            "a_status": "status",
            "ur_intro": "introducer_id",
            "ur_status": "status",
            "ur_message": "message",
            "ur_pin": "pin",
            "ur_updated": "updated_at",
        }
    return {
        "p_investor": "investorId",
        "p_phone": "phone",
        "p_name": "name",
        "p_email": "email",
        "p_address": "address",
        "p_introducer": "introducer",
        "p_mpin": "mpin",
        "p_status": "status",
        "p_total": "totalInvestment",
        "a_agent": "agentId",
        "a_phone": "phone",
        "a_name": "name",
        "a_email": "email",
        "a_location": "location",
        "a_introducer": "introducer",
        "a_mpin": "mpin",
        "a_profile": "profileImage",
        "a_status": "status",
        "ur_intro": "introducerId",
        "ur_status": "status",
        "ur_message": "message",
        "ur_pin": "pin",
        "ur_updated": "updatedAt",
    }


def introducer_id_from_row(row: dict) -> Optional[str]:
    v = row.get("introducerId")
    if v is not None and str(v).strip() != "":
        return str(v).strip()
    v = row.get("introducer_id")
    if v is not None and str(v).strip() != "":
        return str(v).strip()
    return None


def normalize_user_request_row(row: dict) -> dict:
    created = row.get("created_at")
    if created is None:
        created = row.get("createdAt")
    updated = row.get("updated_at")
    if updated is None:
        updated = row.get("updatedAt")
    intro = introducer_id_from_row(row)
    return {
        "id": row.get("id"),
        "phone": row.get("phone"),
        "role": row.get("role"),
        "name": row.get("name"),
        "introducerId": intro,
        "status": row.get("status"),
        "message": row.get("message"),
        "pin": row.get("pin"),
        "createdAt": created,
        "updatedAt": updated,
    }
