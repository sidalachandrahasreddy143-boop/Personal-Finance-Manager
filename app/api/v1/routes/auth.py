"""Authentication endpoints."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.openapi import ERROR_RESPONSES
from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, get_user_repository
from app.core.errors import AuthenticationError, ConflictError
from app.core.rate_limit import enforce_rate_limit
from app.core.security import create_access_token, verify_password
from app.models import User
from app.repositories.users import UserRepository
from app.schemas.auth import LoginRequest, PasswordChange, Token, UserCreate, UserRead, UserUpdate
from app.schemas.common import Message
from app.services.ledger import LedgerService

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_token(db: Session, user: User) -> Token:
    """Stamp the login time and mint a bearer token for ``user``."""
    user.last_login_at = dt.datetime.now(dt.UTC)
    db.flush()
    return Token(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserRead.model_validate(user),
    )


def _authenticate(users: UserRepository, db: Session, email: str, password: str) -> Token:
    user = users.get_by_email(email)
    # Identical message and code path for unknown email vs. wrong password.
    if user is None or not verify_password(password, user.hashed_password):
        raise AuthenticationError("Incorrect email or password")
    if not user.is_active:
        raise AuthenticationError("This account has been deactivated")
    return _issue_token(db, user)


@router.post(
    "/register",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    responses=ERROR_RESPONSES,
)
def register(
    payload: UserCreate,
    request: Request,
    db: DbSession,
    users: UserRepository = Depends(get_user_repository),
) -> Token:
    """Register a user, seed a starter set of categories, and return a token."""
    enforce_rate_limit(request, bucket="auth")

    if users.get_by_email(payload.email) is not None:
        raise ConflictError("An account with that email already exists")

    user = users.create_user(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        currency=payload.currency,
    )
    LedgerService(db).seed_default_categories(user.id)
    return _issue_token(db, user)


@router.post("/token", response_model=Token, summary="OAuth2 password flow (Swagger *Authorize*)")
def login_form(
    request: Request,
    db: DbSession,
    form: OAuth2PasswordRequestForm = Depends(),
    users: UserRepository = Depends(get_user_repository),
) -> Token:
    """Standard form login so the Swagger UI **Authorize** button works."""
    enforce_rate_limit(request, bucket="auth")
    return _authenticate(users, db, form.username, form.password)


@router.post("/login", response_model=Token, summary="Log in with a JSON body")
def login_json(
    payload: LoginRequest,
    request: Request,
    db: DbSession,
    users: UserRepository = Depends(get_user_repository),
) -> Token:
    enforce_rate_limit(request, bucket="auth")
    return _authenticate(users, db, payload.email, payload.password)


@router.get("/me", response_model=UserRead, summary="Current user profile")
def read_me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("/me", response_model=UserRead, summary="Update profile")
def update_me(payload: UserUpdate, user: CurrentUser, db: DbSession) -> UserRead:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    db.flush()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.post("/change-password", response_model=Message, summary="Change password")
def change_password(
    payload: PasswordChange,
    user: CurrentUser,
    users: UserRepository = Depends(get_user_repository),
) -> Message:
    if not verify_password(payload.current_password, user.hashed_password):
        raise AuthenticationError("Current password is incorrect")
    users.set_password(user, payload.new_password)
    return Message(detail="Password updated. Existing tokens stay valid until they expire.")
