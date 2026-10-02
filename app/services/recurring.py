"""Recurring rule logic, including safe materialisation of due transactions."""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError
from app.models import RecurringRule, Transaction
from app.repositories.accounts import AccountRepository
from app.repositories.categories import CategoryRepository
from app.repositories.recurring import RecurringRuleRepository
from app.repositories.transactions import TransactionRepository
from app.schemas.ledger import RecurringRuleCreate, RecurringRuleUpdate
from app.services.periods import add_frequency, today_utc

logger = logging.getLogger(__name__)

MAX_CATCHUP_ITERATIONS = 120  # safety valve against runaway rules


class RecurringService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.rules = RecurringRuleRepository(db)
        self.accounts = AccountRepository(db)
        self.categories = CategoryRepository(db)
        self.transactions = TransactionRepository(db)

    # ------------------------------------------------------------------ #
    def create(self, user_id: int, payload: RecurringRuleCreate) -> RecurringRule:
        # The rule has no currency of its own - posted transactions inherit the
        # account's currency at materialisation time.
        self.accounts.get_for_user(user_id, payload.account_id)
        if payload.category_id is not None:
            self.categories.get_for_user(user_id, payload.category_id)
        if payload.end_date and payload.end_date < payload.next_run_on:
            raise BusinessRuleError("end_date must be on or after next_run_on")
        return self.rules.create(user_id=user_id, **payload.model_dump())

    def list_rules(self, user_id: int, *, include_inactive: bool = False) -> list[RecurringRule]:
        """Named ``list_rules`` (not ``list``) so the builtin stays usable in annotations."""
        return self.rules.list_for_user(user_id, include_inactive=include_inactive)

    def get(self, user_id: int, rule_id: int) -> RecurringRule:
        return self.rules.get_for_user(user_id, rule_id)

    def update(self, user_id: int, rule_id: int, payload: RecurringRuleUpdate) -> RecurringRule:
        rule = self.rules.get_for_user(user_id, rule_id)
        return self.rules.update(rule, **payload.model_dump(exclude_unset=True))

    def delete(self, user_id: int, rule_id: int) -> None:
        self.rules.delete(self.rules.get_for_user(user_id, rule_id))

    def upcoming(self, user_id: int, *, days: int = 30) -> list[RecurringRule]:
        return self.rules.upcoming(user_id, days=days, as_of=today_utc())

    # ------------------------------------------------------------------ #
    def run_due(self, user_id: int, *, as_of: dt.date | None = None) -> list[Transaction]:
        """Post every transaction that has come due, advancing each rule.

        Idempotent per run: a rule that already points past ``as_of`` is skipped,
        so calling this twice a day cannot double-charge the ledger.
        """
        reference = as_of or today_utc()
        posted: list[Transaction] = []

        for rule in self.rules.due_rules(user_id, reference):
            iterations = 0
            while rule.next_run_on <= reference and iterations < MAX_CATCHUP_ITERATIONS:
                iterations += 1
                if rule.end_date and rule.next_run_on > rule.end_date:
                    rule.is_active = False
                    break

                posted.append(
                    self.transactions.create(
                        user_id=user_id,
                        account_id=rule.account_id,
                        category_id=rule.category_id,
                        recurring_rule_id=rule.id,
                        type=rule.type,
                        amount=rule.amount,
                        currency=rule.account.currency,
                        description=rule.description,
                        merchant=rule.merchant,
                        occurred_on=rule.next_run_on,
                        notes="Posted automatically from a recurring rule",
                        is_recurring=True,
                    )
                )
                rule.next_run_on = add_frequency(rule.next_run_on, rule.frequency, rule.interval)

                if rule.end_date and rule.next_run_on > rule.end_date:
                    rule.is_active = False
                    break

            if iterations >= MAX_CATCHUP_ITERATIONS:  # pragma: no cover - defensive
                logger.warning(
                    "Recurring rule %s hit the catch-up cap; check its schedule", rule.id
                )

        self.db.flush()
        return posted
