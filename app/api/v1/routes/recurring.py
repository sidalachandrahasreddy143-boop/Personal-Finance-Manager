"""Recurring rule endpoints."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query, status

from app.api.openapi import ERROR_RESPONSES, not_found
from app.core.deps import CurrentUser, DbSession
from app.schemas.common import Message
from app.schemas.ledger import (
    RecurringRuleCreate,
    RecurringRuleRead,
    RecurringRuleUpdate,
    RecurringRunResult,
    TransactionRead,
)
from app.services.recurring import RecurringService

router = APIRouter(prefix="/recurring", tags=["recurring"])


@router.get("", response_model=list[RecurringRuleRead], summary="List recurring rules")
def list_rules(
    user: CurrentUser, db: DbSession, include_inactive: bool = Query(False)
) -> list[RecurringRuleRead]:
    return [
        RecurringRuleRead.model_validate(rule)
        for rule in RecurringService(db).list_rules(user.id, include_inactive=include_inactive)
    ]


@router.post(
    "",
    response_model=RecurringRuleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a recurring rule",
    responses=ERROR_RESPONSES,
)
def create_rule(
    payload: RecurringRuleCreate, user: CurrentUser, db: DbSession
) -> RecurringRuleRead:
    return RecurringRuleRead.model_validate(RecurringService(db).create(user.id, payload))


@router.patch(
    "/{rule_id}",
    response_model=RecurringRuleRead,
    summary="Update a rule",
    responses=not_found("Recurring rule does not exist"),
)
def update_rule(
    rule_id: int, payload: RecurringRuleUpdate, user: CurrentUser, db: DbSession
) -> RecurringRuleRead:
    return RecurringRuleRead.model_validate(RecurringService(db).update(user.id, rule_id, payload))


@router.delete(
    "/{rule_id}",
    response_model=Message,
    summary="Delete a rule",
    responses=not_found("Recurring rule does not exist"),
)
def delete_rule(rule_id: int, user: CurrentUser, db: DbSession) -> Message:
    RecurringService(db).delete(user.id, rule_id)
    return Message(detail=f"Recurring rule {rule_id} deleted")


@router.post(
    "/run",
    response_model=RecurringRunResult,
    summary="Post all due transactions",
    description=(
        "Idempotent: posts one transaction per due occurrence and advances "
        "`next_run_on`. Safe to call from cron, a queue worker, or the UI button."
    ),
)
def run_due(
    user: CurrentUser,
    db: DbSession,
    as_of: dt.date | None = Query(None, description="Post as if it were this date"),
) -> RecurringRunResult:
    service = RecurringService(db)
    posted = service.run_due(user.id, as_of=as_of)
    return RecurringRunResult(
        posted=len(posted),
        transactions=[TransactionRead.model_validate(t) for t in posted],
        next_runs=[rule.next_run_on for rule in service.list_rules(user.id)],
    )
