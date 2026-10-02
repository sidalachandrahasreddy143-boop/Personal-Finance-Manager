"""Schemas for accounts, categories, transactions, budgets, goals and rules."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import (
    AccountType,
    BudgetPeriod,
    CategoryKind,
    Frequency,
    GoalStatus,
    TransactionType,
)
from app.schemas.common import Money, MoneyNonNegative, MoneyPositive, ORMModel, Ratio

# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120, examples=["HDFC Savings"])
    type: AccountType = AccountType.BANK
    currency: str = Field(default="INR", min_length=3, max_length=3)
    opening_balance: MoneyNonNegative = Decimal("0.00")
    institution: str | None = Field(default=None, max_length=120)
    opened_on: dt.date | None = None


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: AccountType | None = None
    institution: str | None = Field(default=None, max_length=120)
    opening_balance: MoneyNonNegative | None = None
    is_archived: bool | None = None


class AccountRead(ORMModel):
    id: int
    name: str
    type: AccountType
    currency: str
    opening_balance: Money
    institution: str | None
    opened_on: dt.date | None
    is_archived: bool
    created_at: dt.datetime


class AccountBalance(BaseModel):
    """Account with its dynamically computed current balance."""

    account: AccountRead
    current_balance: Money
    income_total: Money
    expense_total: Money
    transaction_count: int


# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80, examples=["Groceries"])
    kind: CategoryKind = CategoryKind.EXPENSE
    color: str = Field(default="#6366f1", pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    icon: str = Field(default="💸", max_length=8)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    icon: str | None = Field(default=None, max_length=8)
    is_archived: bool | None = None


class CategoryRead(ORMModel):
    id: int
    name: str
    kind: CategoryKind
    color: str
    icon: str
    is_archived: bool


# --------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------- #


class TransactionBase(BaseModel):
    amount: MoneyPositive
    type: TransactionType
    description: str = Field(min_length=1, max_length=255)
    occurred_on: dt.date
    merchant: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("tags")
    @classmethod
    def _normalise_tags(cls, value: list[str]) -> list[str]:
        cleaned = [tag.strip().lower()[:32] for tag in value if tag.strip()]
        return sorted(set(cleaned))


class TransactionCreate(TransactionBase):
    account_id: int
    category_id: int | None = None
    is_recurring: bool = False


class TransactionUpdate(BaseModel):
    amount: MoneyPositive | None = None
    type: TransactionType | None = None
    description: str | None = Field(default=None, min_length=1, max_length=255)
    occurred_on: dt.date | None = None
    merchant: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    tags: list[str] | None = None
    account_id: int | None = None
    category_id: int | None = None


class TransactionRead(ORMModel):
    id: int
    account_id: int
    category_id: int | None
    type: TransactionType
    amount: Money
    currency: str
    description: str
    merchant: str | None
    occurred_on: dt.date
    notes: str | None
    tags: list[str] = Field(default_factory=list)
    is_recurring: bool
    created_at: dt.datetime

    @model_validator(mode="before")
    @classmethod
    def _flatten_tags(cls, data: Any) -> Any:
        """ORM stores tags as CSV; expose them as a list."""
        if hasattr(data, "tag_list"):
            payload = {column.name: getattr(data, column.name) for column in data.__table__.columns}
            payload["tags"] = data.tag_list
            return payload
        return data


class TransactionFilter(BaseModel):
    """Validated filter set for listing transactions."""

    search: str | None = None
    account_id: int | None = None
    category_id: int | None = None
    type: TransactionType | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    min_amount: MoneyNonNegative | None = None
    max_amount: MoneyNonNegative | None = None
    tags: list[str] | None = None
    sort: str = "occurred_on"
    order: str = "desc"


# --------------------------------------------------------------------------- #
# Budgets
# --------------------------------------------------------------------------- #


class BudgetCreate(BaseModel):
    category_id: int
    amount_limit: MoneyPositive
    period: BudgetPeriod = BudgetPeriod.MONTHLY
    period_start: dt.date | None = Field(
        default=None, description="Defaults to the start of the current period."
    )
    alert_threshold: Ratio = Decimal("0.80")
    rollover: bool = False


class BudgetUpdate(BaseModel):
    amount_limit: MoneyPositive | None = None
    alert_threshold: Ratio | None = None
    rollover: bool | None = None
    is_active: bool | None = None


class BudgetRead(ORMModel):
    id: int
    category_id: int
    amount_limit: Money
    period: BudgetPeriod
    period_start: dt.date
    alert_threshold: Ratio
    rollover: bool
    is_active: bool


class BudgetStatus(BaseModel):
    """Budget + live consumption for the current period."""

    budget: BudgetRead
    category_name: str
    category_icon: str
    category_color: str
    spent: Money
    remaining: Money
    used_pct: float
    is_over: bool
    is_alert: bool
    period_end: dt.date
    days_remaining: int
    safe_daily_spend: Money
    projected_spend: Money


# --------------------------------------------------------------------------- #
# Goals
# --------------------------------------------------------------------------- #


class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: MoneyPositive
    saved_amount: MoneyNonNegative = Decimal("0.00")
    target_date: dt.date | None = None
    notes: str | None = None


class GoalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    target_amount: MoneyPositive | None = None
    saved_amount: MoneyNonNegative | None = None
    target_date: dt.date | None = None
    status: GoalStatus | None = None
    notes: str | None = None


class GoalContribution(BaseModel):
    amount: MoneyPositive


class GoalRead(ORMModel):
    id: int
    name: str
    target_amount: Money
    saved_amount: Money
    target_date: dt.date | None
    status: GoalStatus
    notes: str | None
    progress_pct: float


# --------------------------------------------------------------------------- #
# Recurring rules
# --------------------------------------------------------------------------- #


class RecurringRuleCreate(BaseModel):
    account_id: int
    category_id: int | None = None
    description: str = Field(min_length=1, max_length=255)
    merchant: str | None = Field(default=None, max_length=120)
    type: TransactionType
    amount: MoneyPositive
    frequency: Frequency = Frequency.MONTHLY
    interval: int = Field(default=1, ge=1, le=60)
    next_run_on: dt.date
    end_date: dt.date | None = None


class RecurringRuleUpdate(BaseModel):
    amount: MoneyPositive | None = None
    description: str | None = Field(default=None, min_length=1, max_length=255)
    frequency: Frequency | None = None
    interval: int | None = Field(default=None, ge=1, le=60)
    next_run_on: dt.date | None = None
    end_date: dt.date | None = None
    is_active: bool | None = None


class RecurringRuleRead(ORMModel):
    id: int
    account_id: int
    category_id: int | None
    description: str
    merchant: str | None
    type: TransactionType
    amount: Money
    frequency: Frequency
    interval: int
    next_run_on: dt.date
    end_date: dt.date | None
    is_active: bool


class RecurringRunResult(BaseModel):
    posted: int
    transactions: list[TransactionRead]
    next_runs: list[dt.date]
