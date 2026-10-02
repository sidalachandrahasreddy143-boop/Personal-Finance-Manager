"""Rule-based insight engine.

A deterministic, explainable alternative to "throw an LLM at it": every insight
is derived from an auditable rule with a threshold, so it can be unit tested and
defended in a code review. The optional AI layer (``app/services/ai.py``) can
rephrase these into prose without inventing numbers.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.enums import CategoryKind, TransactionType
from app.repositories.budgets import BudgetRepository
from app.repositories.goals import GoalRepository
from app.repositories.recurring import RecurringRuleRepository
from app.repositories.transactions import TransactionQuery, TransactionRepository
from app.schemas.insights import Insight, InsightReport, InsightSummary
from app.schemas.ledger import BudgetStatus
from app.schemas.reports import CategoryBreakdown
from app.services.budgets import BudgetService
from app.services.periods import today_utc
from app.services.reports import ReportService, _q

# --- thresholds (single source of truth, easy to tune / A-B test) ---------- #
SAVINGS_RATE_GREAT = 20.0
SAVINGS_RATE_OK = 10.0
SPIKE_THRESHOLD_PCT = 20.0
CATEGORY_CONCENTRATION_PCT = 35.0
LARGE_TXN_MULTIPLIER = 3.0
MIN_LARGE_TRANSACTION = 1000.0  # absolute floor so tiny ledgers stay quiet
SUBSCRIPTION_SHARE_PCT = 25.0


class InsightService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.reports = ReportService(db)
        self.budgets = BudgetRepository(db)
        self.transactions = TransactionRepository(db)
        self.goals = GoalRepository(db)
        self.recurring = RecurringRuleRepository(db)

    def generate(
        self, user_id: int, *, date_from: dt.date | None = None, date_to: dt.date | None = None
    ) -> InsightReport:
        as_of = today_utc()
        end = date_to or as_of
        start = date_from or (end - dt.timedelta(days=29))
        period_days = (end - start).days + 1

        cashflow = self.reports.cashflow(user_id, start, end)
        breakdown = self.reports.category_breakdown(
            user_id, start, end, kind=CategoryKind.EXPENSE, compare=True
        )
        budget_statuses = BudgetService(self.db).list_status(user_id, as_of=as_of)

        # ``savings_rate`` is a Decimal on the schema; the rules work in floats.
        savings_rate = float(cashflow.savings_rate)

        insights: list[Insight] = []
        insights.extend(self._savings_rate_insights(savings_rate, cashflow.net))
        insights.extend(self._spending_change_insights(cashflow.expense_total, breakdown))
        insights.extend(self._concentration_insight(breakdown))
        insights.extend(self._budget_insights(budget_statuses))
        insights.extend(
            self._large_transaction_insight(user_id, start, end, cashflow.expense_total)
        )
        insights.extend(self._goal_insight(user_id))
        insights.extend(self._recurring_insight(user_id, cashflow.income_total))

        top_item = breakdown.items[0] if breakdown.items else None
        alerts = sum(1 for status in budget_statuses if status.is_alert)
        summary = InsightSummary(
            total_income=cashflow.income_total,
            total_expense=cashflow.expense_total,
            net=cashflow.net,
            savings_rate=savings_rate,
            top_category=top_item.name if top_item else None,
            top_category_amount=top_item.total if top_item else None,
            budget_alerts=alerts,
            health_score=self.health_score(savings_rate, budget_statuses),
        )

        return InsightReport(
            generated_at=dt.datetime.now(dt.UTC),
            period_days=period_days,
            summary=summary,
            insights=insights,
        )

    # ------------------------------------------------------------------ #
    def health_score(
        self, savings_rate: float | Decimal, budget_statuses: Sequence[BudgetStatus]
    ) -> int:
        """0-100 composite: 60% savings behaviour, 40% budget adherence."""
        rate = float(savings_rate)
        savings_component = max(0.0, min(rate / 30.0, 1.0)) * 60
        if budget_statuses:
            on_track = sum(1 for status in budget_statuses if not status.is_over)
            budget_component = on_track / len(budget_statuses) * 40
        else:
            budget_component = 20  # neutral when the user has no budgets yet
        return int(round(savings_component + budget_component))

    # --- individual rules ---------------------------------------------- #
    def _savings_rate_insights(self, rate: float, net: Decimal) -> list[Insight]:
        if rate >= SAVINGS_RATE_GREAT:
            return [
                Insight(
                    code="savings-rate-strong",
                    level="success",
                    title="Strong savings rate",
                    message=(
                        f"You kept {rate:.1f}% of your income this period. "
                        "Sustaining above 20% is what builds real wealth."
                    ),
                    change_pct=rate,
                    action="Consider moving the surplus into an investment account.",
                )
            ]
        if rate >= SAVINGS_RATE_OK:
            return [
                Insight(
                    code="savings-rate-ok",
                    level="info",
                    title="Decent savings rate",
                    message=(
                        f"You saved {rate:.1f}% of income. " "Aim for 20% to accelerate your goals."
                    ),
                    change_pct=rate,
                )
            ]
        level = "danger" if net < 0 else "warning"
        title = "Spending exceeds income" if net < 0 else "Low savings rate"
        return [
            Insight(
                code="savings-rate-low",
                level=level,
                title=title,
                message=(
                    f"Your savings rate is {rate:.1f}%. "
                    + (
                        "You are drawing down savings this period."
                        if net < 0
                        else "Small reductions in the top categories will compound quickly."
                    )
                ),
                metric=net,
                action=(
                    "Review the top spending categories and set a budget on " "the biggest one."
                ),
            )
        ]

    def _spending_change_insights(
        self, total_expense: Decimal, breakdown: CategoryBreakdown
    ) -> list[Insight]:
        insights: list[Insight] = []
        items = breakdown.items
        previous_total = sum((item.previous_total for item in items), Decimal("0.00"))

        if previous_total > 0:
            change = float((total_expense - previous_total) / previous_total * 100)
            if change >= SPIKE_THRESHOLD_PCT:
                insights.append(
                    Insight(
                        code="spending-spike",
                        level="warning",
                        title=f"Spending up {change:.0f}% vs the previous period",
                        message=(
                            f"You spent {_q(total_expense)} this period versus "
                            f"{_q(previous_total)} "
                            "before. Worth a look before it becomes the new normal."
                        ),
                        metric=_q(total_expense - previous_total),
                        change_pct=round(change, 2),
                    )
                )
            elif change <= -SPIKE_THRESHOLD_PCT:
                insights.append(
                    Insight(
                        code="spending-drop",
                        level="success",
                        title=f"Spending down {abs(change):.0f}%",
                        message=(
                            f"You spent {_q(previous_total - total_expense)} less "
                            "than last period."
                        ),
                        metric=_q(previous_total - total_expense),
                        change_pct=round(change, 2),
                    )
                )

        movers = sorted(
            (i for i in items if i.change_pct is not None and i.change_pct > 0),
            key=lambda i: i.change_pct or 0,
            reverse=True,
        )
        for mover in movers[:2]:
            if mover.change_pct and mover.change_pct >= 50 and mover.total > 0:
                insights.append(
                    Insight(
                        code=f"category-jump-{mover.category_id}",
                        level="warning",
                        title=f"{mover.name} jumped {mover.change_pct:.0f}%",
                        message=(
                            f"{mover.name} went from {mover.previous_total} to {mover.total} "
                            f"across {mover.transaction_count} transaction(s)."
                        ),
                        metric=mover.total,
                        change_pct=mover.change_pct,
                    )
                )
        return insights

    def _concentration_insight(self, breakdown: CategoryBreakdown) -> list[Insight]:
        items = breakdown.items
        if not items:
            return []
        top = items[0]
        if top.share_pct >= CATEGORY_CONCENTRATION_PCT:
            return [
                Insight(
                    code="category-concentration",
                    level="info",
                    title=f"{top.name} is {top.share_pct:.0f}% of your spending",
                    message=(
                        f"{top.name} accounts for {top.share_pct:.1f}% of expenses "
                        f"({top.total}). Diversifying spend or renegotiating that line item "
                        "usually frees up the most money."
                    ),
                    metric=top.total,
                )
            ]
        return []

    def _budget_insights(self, statuses: Sequence[BudgetStatus]) -> list[Insight]:
        insights: list[Insight] = []
        for status in statuses:
            if status.is_over:
                overspend = status.spent - status.budget.amount_limit
                insights.append(
                    Insight(
                        code=f"budget-over-{status.budget.id}",
                        level="danger",
                        title=f"{status.category_name} is over budget",
                        message=(
                            f"You have spent {status.spent} of "
                            f"{status.budget.amount_limit} "
                            f"({status.used_pct:.0f}%) with "
                            f"{status.days_remaining} day(s) left."
                        ),
                        metric=_q(overspend),
                        action=(
                            "Pause discretionary spend in this category for the "
                            "rest of the period."
                        ),
                    )
                )
            elif status.is_alert:
                insights.append(
                    Insight(
                        code=f"budget-warning-{status.budget.id}",
                        level="warning",
                        title=f"{status.category_name} is nearly spent",
                        message=(
                            f"{status.used_pct:.0f}% of the "
                            f"{status.budget.amount_limit} budget is used. "
                            f"Safe daily spend: {status.safe_daily_spend} "
                            f"for {status.days_remaining} day(s)."
                        ),
                        metric=status.remaining,
                    )
                )
        return insights

    def _large_transaction_insight(
        self, user_id: int, date_from: dt.date, date_to: dt.date, total_expense: Decimal
    ) -> list[Insight]:
        rows = self.transactions.top_transactions(user_id, date_from, date_to, limit=5)
        if not rows:
            return []

        largest = rows[0]
        amount = largest.amount

        expense_txns = self.transactions.count(
            self.transactions.build_query(
                user_id,
                TransactionQuery(
                    date_from=date_from, date_to=date_to, type=TransactionType.EXPENSE
                ),
            )
        )
        if expense_txns < 3:  # too little history for "unusual" to mean anything
            return []

        average = total_expense / expense_txns
        threshold = average * Decimal(str(LARGE_TXN_MULTIPLIER))
        if amount >= threshold and amount >= Decimal(str(MIN_LARGE_TRANSACTION)):
            return [
                Insight(
                    code="large-transaction",
                    level="info",
                    title="Unusually large transaction",
                    message=(
                        f"'{largest.description}' on {largest.occurred_on} for {_q(amount)} "
                        "stands out "
                        "against your typical spend. Confirm it is expected "
                        "(or flag it for review)."
                    ),
                    metric=_q(amount),
                )
            ]
        return []

    def _goal_insight(self, user_id: int) -> list[Insight]:
        goals = [g for g in self.goals.list_for_user(user_id) if g.status.value == "active"]
        if not goals:
            return [
                Insight(
                    code="no-goals",
                    level="info",
                    title="No active savings goals",
                    message=(
                        "Goals turn leftover money into directed savings. "
                        "Setting one takes a minute."
                    ),
                    action=(
                        "Create a goal (for example a 6-month emergency fund) " "in the Goals tab."
                    ),
                )
            ]

        at_risk = [g for g in goals if g.target_date and g.progress_pct < 100]
        insights: list[Insight] = []
        for goal in at_risk:
            days_left = (goal.target_date - today_utc()).days  # type: ignore[operator]
            if days_left <= 0:
                continue
            remaining = Decimal(goal.target_amount) - Decimal(goal.saved_amount)
            months_left = max(Decimal(days_left) / Decimal(30), Decimal(1))
            monthly_needed = _q(remaining / months_left)
            insights.append(
                Insight(
                    code=f"goal-plan-{goal.id}",
                    level="info",
                    title=f"{goal.progress_pct:.0f}% towards {goal.name}",
                    message=(
                        f"{remaining} to go in {days_left} day(s) - about "
                        f"{monthly_needed} per month."
                    ),
                    metric=remaining,
                )
            )
        return insights

    def _recurring_insight(self, user_id: int, income: Decimal) -> list[Insight]:
        active = [
            rule
            for rule in self.recurring.list_for_user(user_id)
            if rule.type.value == TransactionType.EXPENSE.value
        ]
        if not active:
            return []

        monthly = Decimal("0.00")
        for rule in active:
            amount = Decimal(rule.amount)
            monthly += {
                "daily": amount * 30,
                "weekly": amount * Decimal("4.33"),
                "monthly": amount,
                "yearly": amount / 12,
            }[rule.frequency.value]

        share = float(monthly / income * 100) if income else 0.0
        if income and share >= SUBSCRIPTION_SHARE_PCT:
            return [
                Insight(
                    code="recurring-load",
                    level="warning",
                    title="Fixed commitments are heavy",
                    message=(
                        f"Recurring expenses total about {_q(monthly)} per month - "
                        f"{share:.0f}% of your income. Cancel or renegotiate the "
                        "weakest ones."
                    ),
                    metric=_q(monthly),
                    change_pct=round(share, 2),
                )
            ]
        return [
            Insight(
                code="recurring-summary",
                level="info",
                title=f"{len(active)} recurring commitment(s)",
                message=f"About {_q(monthly)} per month is committed automatically.",
                metric=_q(monthly),
            )
        ]
