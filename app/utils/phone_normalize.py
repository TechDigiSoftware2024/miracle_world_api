"""Normalize Indian mobile numbers for DB lookup and MSG91 (E.164-style 91xxxxxxxxxx)."""


def normalize_phone_digits(phone: str) -> str:
    """Return digits only; 10-digit national number when possible (India)."""
    cleaned = "".join(c for c in phone if c.isdigit())
    if len(cleaned) == 12 and cleaned.startswith("91"):
        return cleaned[2:]
    if len(cleaned) == 11 and cleaned.startswith("0"):
        return cleaned[1:]
    if len(cleaned) >= 10:
        return cleaned[-10:]
    return cleaned


def format_phone_msg91(phone: str) -> str:
    """MSG91 expects mobile like 91XXXXXXXXXX (no +)."""
    d = normalize_phone_digits(phone)
    if len(d) == 10:
        return f"91{d}"
    return d


def is_plausible_in_mobile(phone: str) -> bool:
    d = normalize_phone_digits(phone)
    return len(d) == 10
