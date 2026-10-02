"""Transaction model - the heart of the ledger."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import TransactionType

if TYPE_CHECKING:  # pragma: no cover
    from app.models.account import Account
    from app.models.category import Category
    from app.models.recurring import RecurringRule
    from app.models.user import User


class Transaction(Base, TimestampMixin):
    """A single money movement.

    Amounts are always stored as **positive** decimals; the direction is
    carried by :class:`TransactionType`. That keeps arithmetic and reporting
    unambiguous (``SUM(CASE WHEN type = 'income' ...)``).
    """

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_transactions_user_occurred_on", "user_id", "occurred_on"),
        Index("ix_transactions_user_category", "user_id", "category_id"),
        Index("ix_transactions_user_merchant", "user_id", "merchant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    recurring_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurring_rules.id", ondelete="SET NULL"), index=True
    )

    type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, native_enum=False, length=10), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant: Mapped[str | None] = mapped_column(String(120))
    occurred_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[str | None] = mapped_column(String(255))
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="transactions")
    account: Mapped[Account] = relationship(back_populates="transactions")
    category: Mapped[Category | None] = relationship(back_populates="transactions")
    recurring_rule: Mapped[RecurringRule | None] = relationship(back_populates="transactions")

    # --- convenience helpers -------------------------------------------------
    @property
    def signed_amount(self) -> Decimal:
        """Positive for income, negative for expense, zero for transfers."""
        if self.type is TransactionType.INCOME:
            return self.amount
        if self.type is TransactionType.EXPENSE:
            return -self.amount
        return Decimal("0.00")

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]
