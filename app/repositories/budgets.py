"""Budget data access."""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.errors import NotFoundError
from app.models import Budget
from app.models.enums import BudgetPeriod
from app.repositories.base import BaseRepository


class BudgetRepository(BaseRepository[Budget]):
    model = Budget

    def list_for_user(
        self,
        user_id: int,
        *,
        period_start: object | None = None,
        include_inactive: bool = False,
    ) -> list[Budget]:
        stmt = select(Budget).where(Budget.user_id == user_id)
        if period_start is not None:
            stmt = stmt.where(Budget.period_start == period_start)
        if not include_inactive:
            stmt = stmt.where(Budget.is_active.is_(True))
        return list(
            self.db.scalars(stmt.order_by(Budget.period_start.desc(), Budget.id.desc())).all()
        )

    def get_for_user(self, user_id: int, budget_id: int) -> Budget:
        budget = self.db.scalar(
            select(Budget).where(Budget.id == budget_id, Budget.user_id == user_id)
        )
        if budget is None:
            raise NotFoundError(f"Budget {budget_id} does not exist")
        return budget

    def find_envelope(
        self, user_id: int, category_id: int, period: BudgetPeriod, period_start: object
    ) -> Budget | None:
        return self.db.scalar(
            select(Budget).where(
                Budget.user_id == user_id,
                Budget.category_id == category_id,
                Budget.period == period,
                Budget.period_start == period_start,
            )
        )

    def count_active(self, user_id: int) -> int:
        return int(
            self.db.scalar(
                select(func.count(Budget.id)).where(
                    Budget.user_id == user_id, Budget.is_active.is_(True)
                )
            )
            or 0
        )
