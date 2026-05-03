import random

from app.db.database import supabase


def generate_participant_id(*, id_column: str = "participantId") -> str:
    """Generate a unique participant ID in format MWP + 6 digits."""
    while True:
        new_id = f"MWP{random.randint(100000, 999999)}"
        result = (
            supabase.table("participants")
            .select(id_column)
            .eq(id_column, new_id)
            .execute()
        )
        if not result.data:
            return new_id


def generate_partner_id(*, id_column: str = "partnerId") -> str:
    """Generate a unique partner ID in format MWCP + 6 digits."""
    while True:
        new_id = f"MWCP{random.randint(100000, 999999)}"
        result = (
            supabase.table("partners")
            .select(id_column)
            .eq(id_column, new_id)
            .execute()
        )
        if not result.data:
            return new_id


def generate_admin_id(*, id_column: str = "adminId") -> str:
    """Generate a unique admin ID in format MWA + 6 digits."""
    while True:
        new_id = f"MWA{random.randint(100000, 999999)}"
        result = (
            supabase.table("admins")
            .select(id_column)
            .eq(id_column, new_id)
            .execute()
        )
        if not result.data:
            return new_id
