"""Budget endpoints."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query, status

from app.api.openapi import ERROR_RESPONSES, not_found
from app.core.deps import CurrentUser, DbSession
from app.schemas.common import Message
from app.schemas.ledger import BudgetCreate, BudgetRead, BudgetStatus, BudgetUpdate
from app.services.budgets import BudgetService

router = APIRouter(prefix="/budgets", tags=["budgets"])


@router.get(
    "",
    response_model=list[BudgetStatus],
    summary="List budgets with live utilisation",
    description=(
        "Each envelope returns spend for its current window, remaining amount, "
        "projected period-end spend and a safe daily spend for the days left."
    ),
    responses=ERROR_RESPONSES,
)
def list_budgets(
    user: CurrentUser,
    db: DbSession,
    period_start: dt.date | None = Query(None, description="Filter to one budget window"),
    as_of: dt.date | None = Query(None, description="Evaluate as if it were this date"),
) -> list[BudgetStatus]:
    return BudgetService(db).list_status(user.id, period_start=period_start, as_of=as_of)


@router.post(
    "",
    response_model=BudgetRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a budget",
    responses=ERROR_RESPONSES,
)
def create_budget(payload: BudgetCreate, user: CurrentUser, db: DbSession) -> BudgetRead:
    return BudgetRead.model_validate(BudgetService(db).create(user.id, payload))


@router.get(
    "/{budget_id}",
    response_model=BudgetStatus,
    summary="Get one budget's status",
    responses=not_found("Budget does not exist"),
)
def get_budget(budget_id: int, user: CurrentUser, db: DbSession) -> BudgetStatus:
    service = BudgetService(db)
    return service.status(user.id, service.budgets.get_for_user(user.id, budget_id))


@router.patch(
    "/{budget_id}",
    response_model=BudgetRead,
    summary="Update a budget",
    responses=not_found("Budget does not exist"),
)
def update_budget(
    budget_id: int, payload: BudgetUpdate, user: CurrentUser, db: DbSession
) -> BudgetRead:
    return BudgetRead.model_validate(BudgetService(db).update(user.id, budget_id, payload))


@router.delete(
    "/{budget_id}",
    response_model=Message,
    summary="Delete a budget",
    responses=not_found("Budget does not exist"),
)
def delete_budget(budget_id: int, user: CurrentUser, db: DbSession) -> Message:
    BudgetService(db).delete(user.id, budget_id)
    return Message(detail=f"Budget {budget_id} deleted")
