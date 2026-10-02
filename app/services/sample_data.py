"""Deterministic sample-data generator.

Used by two callers: ``python -m app.scripts.seed_demo`` (demo account) and
``POST /api/v1/data/sample`` (the dashboard's *Load sample data* button). One
source of truth keeps demos, screenshots and manual testing reproducible.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError
from app.models import Account, Budget, Category, Goal, RecurringRule, Transaction
from app.models.enums import AccountType, BudgetPeriod, CategoryKind, Frequency, TransactionType
from app.repositories.categories import DEFAULT_CATEGORIES
from app.services.ledger import LedgerService
from app.services.periods import add_months, month_end, month_start, today_utc

RANDOM_SEED = 20260901

# (category, merchant, descriptions, min, max, occurrences per month)
EXPENSE_PLAN: tuple[tuple[str, str, tuple[str, ...], Decimal, Decimal, int], ...] = (
    ("Rent", "Landlord", ("Monthly rent",), Decimal("18000"), Decimal("18000"), 1),
    (
        "Groceries",
        "BigBasket",
        ("Weekly groceries", "BigBasket order", "Zepto order"),
        Decimal("900"),
        Decimal("2600"),
        4,
    ),
    (
        "Dining",
        "Swiggy",
        ("Swiggy dinner", "Zomato lunch", "Cafe with friends"),
        Decimal("180"),
        Decimal("1200"),
        6,
    ),
    (
        "Transport",
        "Uber",
        ("Uber ride", "Metro recharge", "Petrol top-up"),
        Decimal("120"),
        Decimal("1800"),
        5,
    ),
    (
        "Utilities",
        "Jio Fiber",
        ("Broadband bill", "Electricity bill", "Mobile recharge"),
        Decimal("300"),
        Decimal("2400"),
        3,
    ),
    (
        "Entertainment",
        "Netflix",
        ("Netflix subscription", "Movie tickets", "Spotify"),
        Decimal("199"),
        Decimal("900"),
        2,
    ),
    (
        "Shopping",
        "Amazon",
        ("Amazon order", "Flipkart order"),
        Decimal("400"),
        Decimal("4500"),
        2,
    ),
    (
        "Health",
        "Apollo Pharmacy",
        ("Pharmacy", "Gym membership", "Doctor visit"),
        Decimal("250"),
        Decimal("2000"),
        2,
    ),
    ("Education", "Udemy", ("Udemy course", "Technical books"), Decimal("499"), Decimal("2500"), 1),
)

BUDGET_PLAN: tuple[tuple[str, str], ...] = (
    ("Groceries", "12000"),
    ("Dining", "6000"),
    ("Transport", "5000"),
    ("Entertainment", "3000"),
)


@dataclass(slots=True)
class SampleDataSummary:
    accounts: int = 0
    categories: int = 0
    transactions: int = 0
    budgets: int = 0
    goals: int = 0
    rules: int = 0


def generate_sample_data(
    db: Session, user_id: int, *, months: int = 6, seed: int = RANDOM_SEED
) -> SampleDataSummary:
    """Populate an account with realistic history.

    Refuses to run twice for the same user unless the existing rows are removed
    first - duplicate sample data would make the dashboard numbers nonsense.
    """
    existing = db.scalar(select(func.count(Transaction.id)).where(Transaction.user_id == user_id))
    if existing:
        raise BusinessRuleError(
            "This account already has transactions. Delete them (or use the reset flag in "
            "the CLI) before loading sample data."
        )

    rng = random.Random(seed)
    today = today_utc()
    summary = SampleDataSummary()

    # --- accounts ------------------------------------------------------- #
    accounts = {
        "main": Account(
            user_id=user_id,
            name="HDFC Savings",
            type=AccountType.BANK,
            opening_balance=Decimal("45000"),
            institution="HDFC Bank",
        ),
        "cash": Account(
            user_id=user_id,
            name="Cash Wallet",
            type=AccountType.CASH,
            opening_balance=Decimal("5000"),
        ),
        "card": Account(
            user_id=user_id,
            name="ICICI Credit Card",
            type=AccountType.CREDIT_CARD,
            opening_balance=Decimal("0"),
            institution="ICICI Bank",
        ),
        "invest": Account(
            user_id=user_id,
            name="Zerodha Investments",
            type=AccountType.INVESTMENT,
            opening_balance=Decimal("120000"),
            institution="Zerodha",
        ),
    }

    # Reuse the caller's account as the primary one when they already have any.
    primary = db.scalar(
        select(Account).where(Account.user_id == user_id).order_by(Account.id.asc()).limit(1)
    )
    to_create = [accounts[key] for key in ("main", "cash", "card", "invest") if primary is None]
    if primary is not None:
        accounts["main"] = primary
        to_create = [accounts["cash"], accounts["card"], accounts["invest"]]
    db.add_all(to_create)
    summary.accounts = len(to_create)

    # --- categories ------------------------------------------------------ #
    LedgerService(db).seed_default_categories(user_id)
    db.flush()

    categories = {
        category.name: category
        for category in db.scalars(select(Category).where(Category.user_id == user_id)).all()
    }
    summary.categories = len(categories)

    # --- transactions ----------------------------------------------------- #
    transactions: list[Transaction] = []
    for months_ago in range(months - 1, -1, -1):
        anchor = month_start(add_months(today, -months_ago))
        last_day = month_end(anchor)
        # The month in progress only gets its proportional share of activity,
        # otherwise every expense would be squeezed onto the first day or two
        # and the KPIs would look absurd.
        is_current_month = months_ago == 0
        window_days = today.day if is_current_month else last_day.day

        transactions.append(
            Transaction(
                user_id=user_id,
                account_id=accounts["main"].id,
                category_id=categories["Salary"].id,
                type=TransactionType.INCOME,
                amount=Decimal("85000") + Decimal(rng.choice([0, 2500, 5000])),
                currency=accounts["main"].currency,
                description="Monthly salary - Acme Corp",
                merchant="Acme Corp",
                occurred_on=anchor if not is_current_month else min(anchor, today),
                tags="salary",
                is_recurring=True,
            )
        )
        if rng.random() < 0.45:
            transactions.append(
                Transaction(
                    user_id=user_id,
                    account_id=accounts["main"].id,
                    category_id=categories["Freelance"].id,
                    type=TransactionType.INCOME,
                    amount=Decimal(rng.randrange(8000, 32000, 500)),
                    currency=accounts["main"].currency,
                    description="Freelance project payout",
                    merchant="Upwork",
                    occurred_on=anchor + dt.timedelta(days=rng.randint(8, 20)),
                    tags="freelance,side-income",
                )
            )

        for name, merchant, descriptions, low, high, occurrences in EXPENSE_PLAN:
            # The two most recent months run ~18% hotter, so the insight engine
            # has a genuine spending spike to detect.
            drift = Decimal("1.18") if months_ago <= 1 else Decimal("1.00")
            planned = occurrences
            if is_current_month:
                planned = max(1, round(occurrences * window_days / last_day.day))
            for _ in range(planned):
                amount = (Decimal(rng.randrange(int(low), int(high) + 10, 10)) * drift).quantize(
                    Decimal("0.01")
                )
                account = accounts["card"] if rng.random() < 0.35 else accounts["main"]
                if name in {"Dining", "Transport"} and rng.random() < 0.4:
                    account = accounts["cash"]
                transactions.append(
                    Transaction(
                        user_id=user_id,
                        account_id=account.id,
                        category_id=categories[name].id,
                        type=TransactionType.EXPENSE,
                        amount=amount,
                        currency=account.currency,
                        description=rng.choice(descriptions),
                        merchant=merchant,
                        occurred_on=anchor + dt.timedelta(days=rng.randint(0, window_days - 1)),
                        tags=name.lower(),
                    )
                )

    # One obvious large purchase so the "unusual transaction" rule fires.
    transactions.append(
        Transaction(
            user_id=user_id,
            account_id=accounts["main"].id,
            category_id=categories["Shopping"].id,
            type=TransactionType.EXPENSE,
            amount=Decimal("42999"),
            currency=accounts["main"].currency,
            description="MacBook Air (work laptop)",
            merchant="Apple Store",
            occurred_on=today - dt.timedelta(days=9),
            tags="electronics,one-off",
            notes="Reimbursable from employer",
        )
    )
    db.add_all(transactions)
    summary.transactions = len(transactions)

    # --- budgets ----------------------------------------------------------- #
    for name, limit in BUDGET_PLAN:
        db.add(
            Budget(
                user_id=user_id,
                category_id=categories[name].id,
                amount_limit=Decimal(limit),
                period=BudgetPeriod.MONTHLY,
                period_start=month_start(today),
                alert_threshold=Decimal("0.80"),
            )
        )
        summary.budgets += 1

    # --- goals -------------------------------------------------------------- #
    db.add_all(
        [
            Goal(
                user_id=user_id,
                name="Emergency fund (6 months)",
                target_amount=Decimal("300000"),
                saved_amount=Decimal("145000"),
                target_date=today + dt.timedelta(days=300),
                notes="Six months of essential expenses.",
            ),
            Goal(
                user_id=user_id,
                name="Japan trip",
                target_amount=Decimal("180000"),
                saved_amount=Decimal("52000"),
                target_date=today + dt.timedelta(days=420),
            ),
            Goal(
                user_id=user_id,
                name="New laptop",
                target_amount=Decimal("120000"),
                saved_amount=Decimal("120000"),
                target_date=today - dt.timedelta(days=20),
            ),
        ]
    )
    summary.goals = 3

    # --- recurring rules ------------------------------------------------------ #
    next_month = month_start(add_months(today, 1))
    db.add_all(
        [
            RecurringRule(
                user_id=user_id,
                account_id=accounts["main"].id,
                category_id=categories["Salary"].id,
                description="Monthly salary - Acme Corp",
                merchant="Acme Corp",
                type=TransactionType.INCOME,
                amount=Decimal("85000"),
                frequency=Frequency.MONTHLY,
                next_run_on=next_month,
            ),
            RecurringRule(
                user_id=user_id,
                account_id=accounts["main"].id,
                category_id=categories["Rent"].id,
                description="Monthly rent",
                merchant="Landlord",
                type=TransactionType.EXPENSE,
                amount=Decimal("18000"),
                frequency=Frequency.MONTHLY,
                next_run_on=next_month.replace(day=5),
            ),
            RecurringRule(
                user_id=user_id,
                account_id=accounts["card"].id,
                category_id=categories["Entertainment"].id,
                description="Netflix subscription",
                merchant="Netflix",
                type=TransactionType.EXPENSE,
                amount=Decimal("649"),
                frequency=Frequency.MONTHLY,
                next_run_on=today + dt.timedelta(days=6),
            ),
            RecurringRule(
                user_id=user_id,
                account_id=accounts["main"].id,
                category_id=categories["Utilities"].id,
                description="Broadband bill",
                merchant="Jio Fiber",
                type=TransactionType.EXPENSE,
                amount=Decimal("999"),
                frequency=Frequency.MONTHLY,
                next_run_on=today + dt.timedelta(days=11),
            ),
        ]
    )
    summary.rules = 4

    db.flush()
    return summary


def default_taxonomy() -> list[tuple[str, CategoryKind, str, str]]:
    """Expose the starter taxonomy to scripts/tests without duplicating it."""
    return list(DEFAULT_CATEGORIES)
