"""Reporting endpoints."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query

from app.api.openapi import ERROR_RESPONSES
from app.core.deps import CurrentUser, DbSession
from app.models.enums import CategoryKind
from app.schemas.reports import (
    CashflowReport,
    CategoryBreakdown,
    MerchantSpend,
    NetWorthReport,
    TopTransactionRow,
    TrendReport,
)
from app.services.periods import default_range
from app.services.reports import ReportService

router = APIRouter(prefix="/reports", tags=["reports"])

DateFrom = dt.date | None


def _resolve(
    date_from: DateFrom, date_to: DateFrom, default_days: int = 90
) -> tuple[dt.date, dt.date]:
    fallback_from, fallback_to = default_range(default_days)
    return date_from or fallback_from, date_to or fallback_to


@router.get(
    "/cashflow",
    response_model=CashflowReport,
    summary="Income vs. expense per month",
    description="Defaults to the last 90 days. `savings_rate` = net / income.",
    responses=ERROR_RESPONSES,
)
def cashflow(
    user: CurrentUser,
    db: DbSession,
    date_from: dt.date | None = Query(None, alias="from"),
    date_to: dt.date | None = Query(None, alias="to"),
    days: int = Query(90, ge=7, le=1095, description="Used when `from` is omitted"),
) -> CashflowReport:
    start, end = _resolve(date_from, date_to, days)
    return ReportService(db).cashflow(user.id, start, end)


@router.get(
    "/categories",
    response_model=CategoryBreakdown,
    summary="Spend (or income) by category",
    description=(
        "Includes each category's share of the total and the change versus the "
        "immediately preceding window of equal length."
    ),
)
def category_breakdown(
    user: CurrentUser,
    db: DbSession,
    kind: CategoryKind = Query(CategoryKind.EXPENSE),
    date_from: dt.date | None = Query(None, alias="from"),
    date_to: dt.date | None = Query(None, alias="to"),
    days: int = Query(30, ge=7, le=1095),
    compare: bool = Query(True, description="Compute previous-window deltas"),
) -> CategoryBreakdown:
    start, end = _resolve(date_from, date_to, days)
    return ReportService(db).category_breakdown(user.id, start, end, kind=kind, compare=compare)


@router.get(
    "/merchants",
    response_model=list[MerchantSpend],
    summary="Top merchants by spend",
)
def merchants(
    user: CurrentUser,
    db: DbSession,
    date_from: dt.date | None = Query(None, alias="from"),
    date_to: dt.date | None = Query(None, alias="to"),
    days: int = Query(90, ge=7, le=1095),
    limit: int = Query(10, ge=1, le=50),
) -> list[MerchantSpend]:
    start, end = _resolve(date_from, date_to, days)
    return ReportService(db).merchants(user.id, start, end, limit=limit)


@router.get(
    "/net-worth",
    response_model=NetWorthReport,
    summary="Assets, liabilities and net worth",
    description=(
        "Balances are computed live: opening balance + income - expenses. "
        "Credit cards and loans with a negative balance count as liabilities."
    ),
)
def net_worth(user: CurrentUser, db: DbSession) -> NetWorthReport:
    return ReportService(db).net_worth(user.id)


@router.get(
    "/trends",
    response_model=TrendReport,
    summary="Month-over-month trends",
    description="Always returns every month in the window, zero-filled, so charts have no gaps.",
)
def trends(
    user: CurrentUser,
    db: DbSession,
    months: int = Query(6, ge=2, le=36),
) -> TrendReport:
    return ReportService(db).trends(user.id, months=months)


@router.get(
    "/top-transactions",
    response_model=list[TopTransactionRow],
    summary="Largest expenses in the window",
)
def top_transactions(
    user: CurrentUser,
    db: DbSession,
    date_from: dt.date | None = Query(None, alias="from"),
    date_to: dt.date | None = Query(None, alias="to"),
    days: int = Query(30, ge=7, le=1095),
    limit: int = Query(10, ge=1, le=50),
) -> list[TopTransactionRow]:
    start, end = _resolve(date_from, date_to, days)
    return ReportService(db).top_transactions(user.id, start, end, limit=limit)
