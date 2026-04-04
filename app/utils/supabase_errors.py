from postgrest.exceptions import APIError


def format_api_error(e: APIError) -> str:
    raw = e.args[0] if e.args else str(e)
    if isinstance(raw, dict):
        msg = raw.get("message") or str(raw)
        if raw.get("details"):
            msg = f"{msg} ({raw['details']})"
        return msg
    return str(raw)
