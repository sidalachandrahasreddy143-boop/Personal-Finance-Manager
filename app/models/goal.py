"""Savings goal model."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import GoalStatus

if TYPE_CHECKING:  # pragma: no cover
    from app.models.user import User


class Goal(Base, TimestampMixin):
    """A savings target, e.g. *Emergency fund* or *Japan trip*."""

    __tablename__ = "goals"
    __table_args__ = (
        CheckConstraint("target_amount > 0", name="target_amount_positive"),
        CheckConstraint("saved_amount >= 0", name="saved_amount_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    saved_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    target_date: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[GoalStatus] = mapped_column(
        Enum(GoalStatus, native_enum=False, length=10), default=GoalStatus.ACTIVE, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="goals")

    @property
    def progress_pct(self) -> Decimal:
        if not self.target_amount:
            return Decimal("0.00")
        return round(min(self.saved_amount / self.target_amount * 100, Decimal("100")), 2)
