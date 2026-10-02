"""Password hashing and JWT tests (pure unit tests)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_is_salted_and_verifiable() -> None:
    password = "Str0ng-pass!"
    first = hash_password(password)
    second = hash_password(password)

    assert first != second, "each hash must use a fresh salt"
    assert first.startswith("$2b$")
    assert verify_password(password, first)
    assert verify_password(password, second)


def test_password_verification_rejects_wrong_password() -> None:
    hashed = hash_password("correct-horse")
    assert not verify_password("battery-staple", hashed)
    assert not verify_password("", hashed)


def test_password_verification_survives_corrupt_hash() -> None:
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_password_longer_than_bcrypt_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="72 bytes"):
        hash_password("x" * 73)


def test_token_round_trip_carries_subject() -> None:
    token = create_access_token(42)
    payload = decode_access_token(token)
    assert payload["sub"] == "42"
    assert payload["typ"] == "access"
    assert "jti" in payload


def test_expired_token_is_rejected() -> None:
    token = create_access_token(1, expires_delta=dt.timedelta(seconds=-5))
    with pytest.raises(InvalidTokenError, match="expired"):
        decode_access_token(token)


def test_tampered_token_is_rejected() -> None:
    token = create_access_token(1)
    header, payload, signature = token.split(".")
    with pytest.raises(InvalidTokenError):
        decode_access_token(f"{header}.{payload}.{signature[:-2]}xy")


def test_garbage_token_is_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token("this.is.not-a-jwt")
