"""Recurring transaction rules (salary, rent, subscriptions...)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Date, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import Frequency, TransactionType

if TYPE_CHECKING:  # pragma: no cover
    from app.models.account import Account
    from app.models.category import Category
    from app.models.transaction import Transaction
    from app.models.user import User


class RecurringRule(Base, TimestampMixin):
    """A template that materialises transactions on a fixed cadence.

    Rules are *not* posted by a background thread inside the API process -
    ``POST /recurring/rules/run`` (or ``python -m app.scripts.run_recurring``)
    materialises everything that is due. That keeps the web tier stateless and
    horizontally scalable.
    """

    __tablename__ = "recurring_rules"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )

    description: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant: Mapped[str | None] = mapped_column(String(120))
    type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, native_enum=False, length=10), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    frequency: Mapped[Frequency] = mapped_column(
        Enum(Frequency, native_enum=False, length=10), default=Frequency.MONTHLY, nullable=False
    )
    interval: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    next_run_on: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[dt.date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="recurring_rules")
    account: Mapped[Account] = relationship()
    category: Mapped[Category | None] = relationship()
    transactions: Mapped[list[Transaction]] = relationship(back_populates="recurring_rule")
