"""Account (wallet / bank / card) model."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import AccountType

if TYPE_CHECKING:  # pragma: no cover
    from app.models.transaction import Transaction
    from app.models.user import User


class Account(Base, TimestampMixin):
    """A place money sits: cash, bank account, credit card, wallet, investment."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[AccountType] = mapped_column(
        Enum(AccountType, native_enum=False, length=20), default=AccountType.BANK, nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    institution: Mapped[str | None] = mapped_column(String(120))
    opened_on: Mapped[dt.date | None] = mapped_column(Date)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="accounts")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="account", cascade="all, delete-orphan", passive_deletes=True
    )
