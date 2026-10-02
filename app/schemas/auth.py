"""Authentication and user schemas."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import ORMModel


class UserCreate(BaseModel):
    email: EmailStr = Field(examples=["asha@example.com"])
    password: str = Field(min_length=8, max_length=72, examples=["Str0ng-pass!"])
    full_name: str | None = Field(default=None, max_length=120, examples=["Asha Rao"])
    currency: str = Field(default="INR", min_length=3, max_length=3, examples=["INR"])


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class UserRead(ORMModel):
    id: int
    email: EmailStr
    full_name: str | None
    currency: str
    is_active: bool
    last_login_at: dt.datetime | None
    created_at: dt.datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Token lifetime in seconds")
    user: UserRead


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"email": "demo@pfm.app", "password": "demo1234"}}
    )

    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)
