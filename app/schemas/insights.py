"""Insight / recommendation schemas."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import Money

InsightLevel = Literal["info", "success", "warning", "danger"]


class Insight(BaseModel):
    """One actionable observation produced by the rules engine."""

    code: str = Field(examples=["spending-spike"])
    level: InsightLevel
    title: str
    message: str
    metric: Money | None = None
    change_pct: float | None = None
    action: str | None = Field(default=None, description="Suggested next step for the user.")


class InsightSummary(BaseModel):
    total_income: Money
    total_expense: Money
    net: Money
    savings_rate: float
    top_category: str | None
    top_category_amount: Money | None
    budget_alerts: int
    health_score: int = Field(ge=0, le=100, description="Simple composite financial health score")


class InsightReport(BaseModel):
    generated_at: dt.datetime
    period_days: int
    summary: InsightSummary
    insights: list[Insight]
