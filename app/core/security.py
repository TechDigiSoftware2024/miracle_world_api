import uuid

from jose import jwt, JWTError  # noqa: F401

from app.core.config import JWT_SECRET_KEY, JWT_ALGORITHM


def create_token(data: dict) -> str:
    payload = data.copy()
    payload["jti"] = str(uuid.uuid4())
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(
        token,
        JWT_SECRET_KEY,
        algorithms=[JWT_ALGORITHM],
        options={"verify_exp": False},
    )
