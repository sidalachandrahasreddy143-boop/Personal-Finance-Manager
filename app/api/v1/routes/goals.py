"""Savings goal endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.openapi import ERROR_RESPONSES, not_found
from app.core.deps import CurrentUser, DbSession
from app.models.enums import GoalStatus
from app.schemas.common import Message
from app.schemas.ledger import GoalContribution, GoalCreate, GoalRead, GoalUpdate
from app.services.goals import GoalService

router = APIRouter(prefix="/goals", tags=["goals"])


@router.get("", response_model=list[GoalRead], summary="List savings goals")
def list_goals(
    user: CurrentUser, db: DbSession, status: GoalStatus | None = Query(None)
) -> list[GoalRead]:
    return [GoalRead.model_validate(g) for g in GoalService(db).list(user.id, status=status)]


@router.post(
    "",
    response_model=GoalRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a goal",
    responses=ERROR_RESPONSES,
)
def create_goal(payload: GoalCreate, user: CurrentUser, db: DbSession) -> GoalRead:
    return GoalRead.model_validate(GoalService(db).create(user.id, payload))


@router.get(
    "/{goal_id}",
    response_model=GoalRead,
    summary="Get one goal",
    responses=not_found("Goal does not exist"),
)
def get_goal(goal_id: int, user: CurrentUser, db: DbSession) -> GoalRead:
    return GoalRead.model_validate(GoalService(db).goals.get_for_user(user.id, goal_id))


@router.patch(
    "/{goal_id}",
    response_model=GoalRead,
    summary="Update a goal",
    responses=not_found("Goal does not exist"),
)
def update_goal(goal_id: int, payload: GoalUpdate, user: CurrentUser, db: DbSession) -> GoalRead:
    return GoalRead.model_validate(GoalService(db).update(user.id, goal_id, payload))


@router.post(
    "/{goal_id}/contributions",
    response_model=GoalRead,
    summary="Add money to a goal",
    description="Automatically marks the goal `achieved` when it reaches 100%.",
    responses=not_found("Goal does not exist"),
)
def contribute(
    goal_id: int, payload: GoalContribution, user: CurrentUser, db: DbSession
) -> GoalRead:
    return GoalRead.model_validate(GoalService(db).contribute(user.id, goal_id, payload.amount))


@router.delete(
    "/{goal_id}",
    response_model=Message,
    summary="Delete a goal",
    responses=not_found("Goal does not exist"),
)
def delete_goal(goal_id: int, user: CurrentUser, db: DbSession) -> Message:
    GoalService(db).delete(user.id, goal_id)
    return Message(detail=f"Goal {goal_id} deleted")
