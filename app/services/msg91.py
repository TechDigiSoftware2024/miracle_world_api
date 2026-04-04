"""MSG91 OTP API v5 (server-side; keep MSG91_AUTH_KEY out of mobile apps)."""

from typing import Any, Optional

import httpx

from app.core.config import MSG91_AUTH_KEY, MSG91_BASE_URL, MSG91_TEMPLATE_ID


class MSG91Error(Exception):
    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.code = code


def _headers() -> dict[str, str]:
    return {
        "authkey": MSG91_AUTH_KEY,
        "Content-Type": "application/json",
    }


def _parse_response(resp: httpx.Response) -> dict[str, Any]:
    try:
        return resp.json()
    except Exception:
        return {"message": resp.text or "Invalid JSON", "type": "error"}


def msg91_send_otp(
    mobile_formatted: str,
    *,
    otp: Optional[str] = None,
    otp_expiry: int = 5,
    otp_length: int = 4,
) -> dict[str, Any]:
    if not MSG91_AUTH_KEY or not MSG91_TEMPLATE_ID:
        raise MSG91Error("MSG91 is not configured (set MSG91_AUTH_KEY and MSG91_TEMPLATE_ID)")

    url = f"{MSG91_BASE_URL.rstrip('/')}/otp"
    body: dict[str, Any] = {
        "template_id": MSG91_TEMPLATE_ID,
        "mobile": mobile_formatted,
        "otp_expiry": str(otp_expiry),
        "otp_length": str(otp_length),
    }
    if otp is not None:
        body["otp"] = otp

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=_headers(), json=body)

    data = _parse_response(resp)
    if resp.status_code in (200, 201) and data.get("type") == "success":
        return {
            "success": True,
            "message": data.get("message") or "OTP sent successfully",
            "request_id": data.get("request_id"),
        }
    raise MSG91Error(
        data.get("message") or "Failed to send OTP",
        code=str(data.get("code")) if data.get("code") is not None else None,
    )


def msg91_retry_otp(mobile_formatted: str, *, retry_type: str = "text") -> dict[str, Any]:
    if not MSG91_AUTH_KEY:
        raise MSG91Error("MSG91 is not configured (set MSG91_AUTH_KEY)")

    url = f"{MSG91_BASE_URL.rstrip('/')}/otp/retry"
    body = {"mobile": mobile_formatted, "retrytype": retry_type}

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=_headers(), json=body)

    data = _parse_response(resp)
    if resp.status_code == 200 and data.get("type") == "success":
        return {
            "success": True,
            "message": data.get("message") or "OTP resent successfully",
            "request_id": data.get("request_id"),
        }
    raise MSG91Error(
        data.get("message") or "Failed to retry OTP",
        code=str(data.get("code")) if data.get("code") is not None else None,
    )


def msg91_verify_otp(mobile_formatted: str, otp: str) -> None:
    if not MSG91_AUTH_KEY:
        raise MSG91Error("MSG91 is not configured (set MSG91_AUTH_KEY)")

    url = f"{MSG91_BASE_URL.rstrip('/')}/otp/verify"
    body = {"mobile": mobile_formatted, "otp": otp}

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=_headers(), json=body)

    data = _parse_response(resp)
    if resp.status_code == 200 and data.get("type") == "success":
        return
    raise MSG91Error(
        data.get("message") or "Invalid OTP",
        code=str(data.get("code")) if data.get("code") is not None else None,
    )
