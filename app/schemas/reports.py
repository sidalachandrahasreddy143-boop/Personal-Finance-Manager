"""Reporting / analytics schemas."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from app.models.enums import AccountType, CategoryKind, TransactionType
from app.schemas.common import Money, Ratio


class CashflowPoint(BaseModel):
    period: str = Field(description="ISO period bucket, e.g. 2026-09 or 2026-W36")
    period_start: dt.date
    income: Money
    expense: Money
    net: Money


class CashflowReport(BaseModel):
    date_from: dt.date
    date_to: dt.date
    granularity: str
    income_total: Money
    expense_total: Money
    net: Money
    savings_rate: Ratio = Field(description="net / income, 0-100")
    average_daily_spend: Money
    points: list[CashflowPoint]


class CategoryBreakdownItem(BaseModel):
    category_id: int | None
    name: str
    icon: str
    color: str
    total: Money
    share_pct: float
    transaction_count: int
    average_amount: Money
    previous_total: Money
    change_pct: float | None = Field(
        default=None, description="Change vs the immediately preceding window"
    )


class CategoryBreakdown(BaseModel):
    kind: CategoryKind
    date_from: dt.date
    date_to: dt.date
    total: Money
    items: list[CategoryBreakdownItem]


class MerchantSpend(BaseModel):
    merchant: str
    total: Money
    transaction_count: int
    average_amount: Money


class AccountTypeBalance(BaseModel):
    type: AccountType
    balance: Money
    account_count: int


class NetWorthReport(BaseModel):
    as_of: dt.date
    assets: Money
    liabilities: Money
    net_worth: Money
    by_type: list[AccountTypeBalance]


class MonthlyTrendPoint(BaseModel):
    month: str
    income: Money
    expense: Money
    net: Money
    savings_rate: Ratio


class TrendReport(BaseModel):
    months: list[MonthlyTrendPoint]
    best_month: str | None
    worst_month: str | None
    average_monthly_income: Money
    average_monthly_expense: Money


class TopTransactionRow(BaseModel):
    id: int
    description: str
    amount: Money
    occurred_on: dt.date
    category: str | None
    account: str
    type: TransactionType
