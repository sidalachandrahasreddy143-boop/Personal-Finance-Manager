"""Insight endpoints (rule engine) plus a one-shot dashboard aggregate."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, DbSession
from app.models.enums import CategoryKind
from app.repositories.transactions import TransactionQuery
from app.schemas.insights import InsightReport
from app.schemas.ledger import BudgetStatus, TransactionRead
from app.schemas.reports import CashflowReport, CategoryBreakdown, NetWorthReport, TrendReport
from app.services.budgets import BudgetService
from app.services.insights import InsightService
from app.services.ledger import LedgerService
from app.services.periods import default_range, month_start, today_utc
from app.services.reports import ReportService

router = APIRouter(tags=["insights"])


@router.get(
    "/insights",
    response_model=InsightReport,
    summary="Rule-based insights and health score",
    description=(
        "Runs deterministic rules over the window: savings rate, spending spikes, "
        "category concentration, budget alerts, unusual transactions, goal plans and "
        "recurring-commitment load. Every insight cites the numbers behind it."
    ),
)
def insights(
    user: CurrentUser,
    db: DbSession,
    date_from: dt.date | None = Query(None, alias="from"),
    date_to: dt.date | None = Query(None, alias="to"),
    days: int = Query(30, ge=7, le=365),
) -> InsightReport:
    start, end = default_range(days) if date_from is None else (date_from, date_to or today_utc())
    return InsightService(db).generate(user.id, date_from=start, date_to=end)


@router.get(
    "/dashboard",
    summary="Everything the dashboard needs in one round trip",
    description=(
        "Composed response for the UI: this-month cashflow, category breakdown, net worth, "
        "6-month trend, budget alerts, recent transactions and top insights. Saves the "
        "client from firing eight requests on load."
    ),
)
def dashboard(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    today = today_utc()
    month_start_date = month_start(today)
    reports = ReportService(db)

    cashflow: CashflowReport = reports.cashflow(user.id, month_start_date, today)
    breakdown: CategoryBreakdown = reports.category_breakdown(
        user.id, month_start_date, today, kind=CategoryKind.EXPENSE
    )
    net_worth: NetWorthReport = reports.net_worth(user.id)
    trends: TrendReport = reports.trends(user.id, months=6)
    budgets: list[BudgetStatus] = BudgetService(db).list_status(user.id)
    insight_report = InsightService(db).generate(user.id, date_from=month_start_date, date_to=today)

    recent, _total = LedgerService(db).list_transactions(
        user.id, TransactionQuery(sort="occurred_on", order="desc"), offset=0, limit=8
    )

    return {
        "as_of": today.isoformat(),
        "month": {
            "label": today.strftime("%B %Y"),
            "income": str(cashflow.income_total),
            "expense": str(cashflow.expense_total),
            "net": str(cashflow.net),
            "savings_rate": cashflow.savings_rate,
            "average_daily_spend": str(cashflow.average_daily_spend),
        },
        "cashflow": cashflow.model_dump(mode="json"),
        "categories": breakdown.model_dump(mode="json"),
        "net_worth": net_worth.model_dump(mode="json"),
        "trends": trends.model_dump(mode="json"),
        "budgets": [b.model_dump(mode="json") for b in budgets],
        "insights": insight_report.model_dump(mode="json"),
        "recent_transactions": [
            TransactionRead.model_validate(t).model_dump(mode="json") for t in recent
        ],
    }
