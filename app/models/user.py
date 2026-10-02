"""User account model."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from app.models.account import Account
    from app.models.budget import Budget
    from app.models.category import Category
    from app.models.goal import Goal
    from app.models.recurring import RecurringRule
    from app.models.transaction import Transaction


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(
        String(3), default=settings.default_currency, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    accounts: Mapped[list[Account]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    categories: Mapped[list[Category]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    budgets: Mapped[list[Budget]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    goals: Mapped[list[Goal]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    recurring_rules: Mapped[list[RecurringRule]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
