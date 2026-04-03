import random

from app.db.database import supabase


def generate_investor_id() -> str:
    """Generate a unique investor ID in format MWP + 6 digits."""
    while True:
        new_id = f"MWP{random.randint(100000, 999999)}"
        result = supabase.table("participants").select("id").eq("investorId", new_id).execute()
        if not result.data:
            return new_id


def generate_agent_id() -> str:
    """Generate a unique agent ID in format MWCP + 6 digits."""
    while True:
        new_id = f"MWCP{random.randint(100000, 999999)}"
        result = supabase.table("partners").select("id").eq("agentId", new_id).execute()
        if not result.data:
            return new_id
