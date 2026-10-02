"""Recurring rule data access."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.core.errors import NotFoundError
from app.models import RecurringRule
from app.repositories.base import BaseRepository


class RecurringRuleRepository(BaseRepository[RecurringRule]):
    model = RecurringRule

    def list_for_user(self, user_id: int, *, include_inactive: bool = False) -> list[RecurringRule]:
        stmt = select(RecurringRule).where(RecurringRule.user_id == user_id)
        if not include_inactive:
            stmt = stmt.where(RecurringRule.is_active.is_(True))
        return list(self.db.scalars(stmt.order_by(RecurringRule.next_run_on.asc())).all())

    def get_for_user(self, user_id: int, rule_id: int) -> RecurringRule:
        rule = self.db.scalar(
            select(RecurringRule).where(
                RecurringRule.id == rule_id, RecurringRule.user_id == user_id
            )
        )
        if rule is None:
            raise NotFoundError(f"Recurring rule {rule_id} does not exist")
        return rule

    def due_rules(self, user_id: int, as_of: dt.date) -> list[RecurringRule]:
        """Active rules whose next run date has arrived (or was missed)."""
        return list(
            self.db.scalars(
                select(RecurringRule)
                .where(
                    RecurringRule.user_id == user_id,
                    RecurringRule.is_active.is_(True),
                    RecurringRule.next_run_on <= as_of,
                )
                .order_by(RecurringRule.next_run_on.asc())
            ).all()
        )

    def upcoming(self, user_id: int, *, days: int = 30, as_of: dt.date) -> list[RecurringRule]:
        horizon = as_of + dt.timedelta(days=days)
        return list(
            self.db.scalars(
                select(RecurringRule)
                .where(
                    RecurringRule.user_id == user_id,
                    RecurringRule.is_active.is_(True),
                    RecurringRule.next_run_on <= horizon,
                )
                .order_by(RecurringRule.next_run_on.asc())
            ).all()
        )
