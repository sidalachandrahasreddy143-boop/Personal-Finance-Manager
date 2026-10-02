"""Reusable FastAPI dependencies (auth, db session, pagination)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AuthenticationError
from app.core.pagination import PageParams, page_params
from app.core.security import InvalidTokenError, decode_access_token
from app.db.session import get_db
from app.models import User
from app.repositories.users import UserRepository

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.api_v1_prefix}/auth/token",
    auto_error=False,
    description="JWT access token issued by /auth/token or /auth/register.",
)


def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Resolve the authenticated user from the ``Authorization: Bearer`` token."""
    if not token:
        raise AuthenticationError(
            "Missing bearer token. Authenticate at /api/v1/auth/token.",
        )
    try:
        payload = decode_access_token(token)
    except InvalidTokenError as exc:
        raise AuthenticationError(str(exc)) from exc

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthenticationError("Token subject is invalid") from exc

    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise AuthenticationError("Token refers to a user that no longer exists")
    if not user.is_active:
        raise AuthenticationError("This account has been deactivated")
    return user


DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
Pagination = Annotated[PageParams, Depends(page_params)]


def get_user_repository(db: DbSession) -> UserRepository:
    return UserRepository(db)
