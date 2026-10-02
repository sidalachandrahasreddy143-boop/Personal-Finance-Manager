"""Budget envelope model."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Date, Enum, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import BudgetPeriod

if TYPE_CHECKING:  # pragma: no cover
    from app.models.category import Category
    from app.models.user import User


class Budget(Base, TimestampMixin):
    """A spending limit for one category over one period.

    Budgets are *period instances* (``period_start`` is the first day of the
    window) rather than open-ended limits, which makes month-over-month
    comparison and rollover trivial to reason about.
    """

    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "category_id", "period", "period_start", name="uq_budgets_envelope"
        ),
        CheckConstraint("amount_limit > 0", name="amount_limit_positive"),
        CheckConstraint("alert_threshold > 0 AND alert_threshold <= 1", name="alert_threshold_pct"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), index=True, nullable=False
    )

    amount_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    period: Mapped[BudgetPeriod] = mapped_column(
        Enum(BudgetPeriod, native_enum=False, length=10),
        default=BudgetPeriod.MONTHLY,
        nullable=False,
    )
    period_start: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    alert_threshold: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), default=Decimal("0.80"), nullable=False
    )
    rollover: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="budgets")
    category: Mapped[Category] = relationship(back_populates="budgets")
