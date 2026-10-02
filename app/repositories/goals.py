"""Savings goal data access."""

from __future__ import annotations

from sqlalchemy import select

from app.core.errors import NotFoundError
from app.models import Goal
from app.models.enums import GoalStatus
from app.repositories.base import BaseRepository


class GoalRepository(BaseRepository[Goal]):
    model = Goal

    def list_for_user(self, user_id: int, *, status: GoalStatus | None = None) -> list[Goal]:
        stmt = select(Goal).where(Goal.user_id == user_id)
        if status is not None:
            stmt = stmt.where(Goal.status == status)
        return list(self.db.scalars(stmt.order_by(Goal.created_at.desc())).all())

    def get_for_user(self, user_id: int, goal_id: int) -> Goal:
        goal = self.db.scalar(select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id))
        if goal is None:
            raise NotFoundError(f"Goal {goal_id} does not exist")
        return goal
