"""Budget envelope logic: creation plus live utilisation and projections."""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError
from app.models import Budget
from app.models.enums import CategoryKind
from app.repositories.budgets import BudgetRepository
from app.repositories.categories import CategoryRepository
from app.repositories.transactions import TransactionRepository
from app.schemas.ledger import BudgetCreate, BudgetStatus, BudgetUpdate
from app.services.periods import period_end_for, period_start_for, today_utc

_CENT = Decimal("0.01")


class BudgetService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.budgets = BudgetRepository(db)
        self.categories = CategoryRepository(db)
        self.transactions = TransactionRepository(db)

    def create(self, user_id: int, payload: BudgetCreate) -> Budget:
        category = self.categories.get_for_user(user_id, payload.category_id)
        if category.kind is not CategoryKind.EXPENSE:
            raise BusinessRuleError(
                f"'{category.name}' is an income category - budgets only track spending."
            )

        period_start = payload.period_start or period_start_for(payload.period, today_utc())
        period_start = period_start_for(payload.period, period_start)  # normalise to window start

        if self.budgets.find_envelope(user_id, category.id, payload.period, period_start):
            raise ConflictError(
                f"A {payload.period.value} budget for '{category.name}' starting {period_start} "
                "already exists"
            )

        return self.budgets.create(
            user_id=user_id,
            category_id=category.id,
            amount_limit=payload.amount_limit,
            period=payload.period,
            period_start=period_start,
            alert_threshold=payload.alert_threshold,
            rollover=payload.rollover,
        )

    def update(self, user_id: int, budget_id: int, payload: BudgetUpdate) -> Budget:
        budget = self.budgets.get_for_user(user_id, budget_id)
        return self.budgets.update(budget, **payload.model_dump(exclude_unset=True))

    def delete(self, user_id: int, budget_id: int) -> None:
        self.budgets.delete(self.budgets.get_for_user(user_id, budget_id))

    def status(self, user_id: int, budget: Budget, *, as_of: dt.date | None = None) -> BudgetStatus:
        """Compute live consumption for one envelope."""
        reference = as_of or today_utc()
        start = budget.period_start
        end = period_end_for(budget.period, start)

        limit = Decimal(budget.amount_limit)

        if budget.rollover:
            # Roll unused budget from the previous window into this one.
            previous_start = period_start_for(budget.period, start - dt.timedelta(days=1))
            previous_end = period_end_for(budget.period, previous_start)
            previous_spent = self.transactions.spend_for_category(
                user_id, budget.category_id, previous_start, previous_end
            )
            limit += max(Decimal("0.00"), limit - previous_spent)

        spent = self.transactions.spend_for_category(user_id, budget.category_id, start, end)
        remaining = limit - spent
        used_pct = float((spent / limit * 100) if limit else Decimal("0"))

        days_remaining = max((end - reference).days, 0) if reference <= end else 0
        elapsed_days = max((min(reference, end) - start).days + 1, 1)
        burn_rate = spent / elapsed_days
        total_days = (end - start).days + 1
        projected = (burn_rate * total_days).quantize(_CENT, rounding=ROUND_HALF_UP)
        safe_daily = (
            (remaining / days_remaining).quantize(_CENT, rounding=ROUND_HALF_UP)
            if days_remaining and remaining > 0
            else Decimal("0.00")
        )

        return BudgetStatus(
            budget=budget,
            category_name=budget.category.name,
            category_icon=budget.category.icon,
            category_color=budget.category.color,
            spent=spent,
            remaining=remaining,
            used_pct=round(used_pct, 2),
            is_over=spent > limit,
            is_alert=used_pct >= float(budget.alert_threshold) * 100,
            period_end=end,
            days_remaining=days_remaining,
            safe_daily_spend=safe_daily,
            projected_spend=projected,
        )

    def list_status(
        self, user_id: int, *, period_start: dt.date | None = None, as_of: dt.date | None = None
    ) -> list[BudgetStatus]:
        budgets = self.budgets.list_for_user(user_id, period_start=period_start)
        return [self.status(user_id, b, as_of=as_of) for b in budgets]
