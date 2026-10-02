"""Savings goal logic."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError
from app.models import Goal
from app.models.enums import GoalStatus
from app.repositories.goals import GoalRepository
from app.schemas.ledger import GoalCreate, GoalUpdate


class GoalService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.goals = GoalRepository(db)

    def create(self, user_id: int, payload: GoalCreate) -> Goal:
        goal = self.goals.create(user_id=user_id, **payload.model_dump())
        self._sync_status(goal)
        return goal

    def list(self, user_id: int, *, status: GoalStatus | None = None) -> list[Goal]:
        return self.goals.list_for_user(user_id, status=status)

    def update(self, user_id: int, goal_id: int, payload: GoalUpdate) -> Goal:
        goal = self.goals.get_for_user(user_id, goal_id)
        goal = self.goals.update(goal, **payload.model_dump(exclude_unset=True))
        self._sync_status(goal)
        return goal

    def contribute(self, user_id: int, goal_id: int, amount: Decimal) -> Goal:
        goal = self.goals.get_for_user(user_id, goal_id)
        if goal.status is GoalStatus.ARCHIVED:
            raise BusinessRuleError("This goal is archived and cannot receive contributions")
        goal.saved_amount = Decimal(goal.saved_amount) + amount
        self.db.flush()
        self._sync_status(goal)
        return goal

    def delete(self, user_id: int, goal_id: int) -> None:
        self.goals.delete(self.goals.get_for_user(user_id, goal_id))

    @staticmethod
    def _sync_status(goal: Goal) -> None:
        """Flip a goal to ``achieved`` once it is fully funded."""
        if goal.status is GoalStatus.ACTIVE and Decimal(goal.saved_amount) >= Decimal(
            goal.target_amount
        ):
            goal.status = GoalStatus.ACHIEVED
