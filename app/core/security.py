"""Password hashing and JWT helpers.

Deliberately dependency-light: ``bcrypt`` for password hashing (salted, adaptive
cost factor) and ``PyJWT`` for stateless bearer tokens.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Final

import bcrypt
import jwt

from app.core.config import settings

_PASSWORD_MAX_BYTES: Final = 72  # bcrypt truncates silently beyond 72 bytes
JWT_SUBJECT: Final = "access"


class InvalidTokenError(Exception):
    """Raised when a token is malformed, expired or has an invalid signature."""


def hash_password(plain_password: str) -> str:
    """Hash a password with bcrypt, returning a ``$2b$`` hash string."""
    password_bytes = plain_password.encode("utf-8")
    if len(password_bytes) > _PASSWORD_MAX_BYTES:
        raise ValueError("Password must be at most 72 bytes long")
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time verification of a password against its bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str | int,
    *,
    expires_delta: dt.timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT access token for ``subject`` (the user id)."""
    now = dt.datetime.now(dt.UTC)
    expire = now + (expires_delta or dt.timedelta(minutes=settings.access_token_expire_minutes))
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": uuid.uuid4().hex,
        "typ": JWT_SUBJECT,
        "iss": settings.app_name,
        **(extra_claims or {}),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate an access token, raising :class:`InvalidTokenError`."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            issuer=settings.app_name,
            options={"require": ["exp", "sub", "iat"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError("Token is invalid") from exc

    if payload.get("typ") != JWT_SUBJECT:
        raise InvalidTokenError("Unexpected token type")
    return payload
