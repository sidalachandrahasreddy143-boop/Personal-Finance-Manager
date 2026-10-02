"""Insight engine tests - every rule is deterministic, so every rule is testable."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import AccountType, CategoryKind, TransactionType
from app.services.periods import previous_window, today_utc
from tests.conftest import (
    create_account,
    create_budget,
    create_category,
    create_transaction,
)


def _codes(payload: dict) -> set[str]:
    return {insight["code"] for insight in payload["insights"]}


def test_strong_savings_rate_is_rewarded(client: TestClient, seeded: dict) -> None:
    headers = seeded["headers"]
    today = today_utc()
    for amount, kind, category in (
        ("100000", "income", seeded["salary_id"]),
        ("50000", "expense", seeded["groceries_id"]),
    ):
        client.post(
            "/api/v1/transactions",
            headers=headers,
            json={
                "account_id": seeded["account_id"],
                "category_id": category,
                "amount": amount,
                "type": kind,
                "description": f"{kind} row",
                "occurred_on": today.isoformat(),
            },
        )

    report = client.get("/api/v1/insights", headers=headers).json()
    assert report["summary"]["savings_rate"] == 50.0
    assert "savings-rate-strong" in _codes(report)
    assert report["summary"]["health_score"] > 60


def test_overspending_is_flagged_as_danger(client: TestClient, seeded: dict) -> None:
    headers = seeded["headers"]
    client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "account_id": seeded["account_id"],
            "category_id": seeded["groceries_id"],
            "amount": "40000",
            "type": "expense",
            "description": "Big spend",
            "occurred_on": today_utc().isoformat(),
        },
    )

    report = client.get("/api/v1/insights", headers=headers).json()
    levels = {insight["level"] for insight in report["insights"]}
    assert "danger" in levels
    assert any(code.startswith("savings-rate-low") for code in _codes(report))


def test_spending_spike_compares_equal_length_windows(
    client: TestClient, db: Session, seeded: dict
) -> None:
    today = today_utc()
    window_start = today - dt.timedelta(days=9)
    previous_start, previous_end = previous_window(window_start, today)

    create_transaction(
        db,
        seeded["user_id"],
        seeded["account"],
        amount="1000",
        type_=TransactionType.EXPENSE,
        category=seeded["groceries"],
        occurred_on=previous_end,
    )
    create_transaction(
        db,
        seeded["user_id"],
        seeded["account"],
        amount="2500",
        type_=TransactionType.EXPENSE,
        category=seeded["groceries"],
        occurred_on=today,
    )
    db.commit()

    report = client.get(
        f"/api/v1/insights?from={window_start.isoformat()}&to={today.isoformat()}",
        headers=seeded["headers"],
    ).json()

    spike = next(i for i in report["insights"] if i["code"] == "spending-spike")
    assert spike["change_pct"] == 150.0
    assert spike["level"] == "warning"
    assert previous_start <= previous_end


def test_budget_breaches_become_danger_insights(
    client: TestClient, db: Session, seeded: dict
) -> None:
    create_budget(db, seeded["user_id"], seeded["groceries"], limit="1000")
    create_transaction(
        db,
        seeded["user_id"],
        seeded["account"],
        amount="1500",
        type_=TransactionType.EXPENSE,
        category=seeded["groceries"],
        occurred_on=today_utc(),
    )
    db.commit()

    report = client.get("/api/v1/insights", headers=seeded["headers"]).json()
    over = next(i for i in report["insights"] if i["code"].startswith("budget-over-"))
    assert over["level"] == "danger"
    assert over["metric"] == "500.00"
    assert report["summary"]["budget_alerts"] == 1


def test_budget_near_limit_produces_a_warning(
    client: TestClient, db: Session, seeded: dict
) -> None:
    create_budget(db, seeded["user_id"], seeded["groceries"], limit="1000")
    create_transaction(
        db,
        seeded["user_id"],
        seeded["account"],
        amount="900",
        type_=TransactionType.EXPENSE,
        category=seeded["groceries"],
        occurred_on=today_utc(),
    )
    db.commit()

    report = client.get("/api/v1/insights", headers=seeded["headers"]).json()
    assert any(code.startswith("budget-warning-") for code in _codes(report))


def test_unusual_large_transaction_is_detected(
    client: TestClient, db: Session, seeded: dict
) -> None:
    for amount, when in (
        ("100", today_utc()),
        ("120", today_utc()),
        ("90", today_utc() - dt.timedelta(days=1)),
        ("25000", today_utc() - dt.timedelta(days=2)),
    ):
        create_transaction(
            db,
            seeded["user_id"],
            seeded["account"],
            amount=amount,
            type_=TransactionType.EXPENSE,
            category=seeded["groceries"],
            occurred_on=when,
            description=f"Spend {amount}",
        )
    db.commit()

    report = client.get("/api/v1/insights", headers=seeded["headers"]).json()
    large = next(i for i in report["insights"] if i["code"] == "large-transaction")
    assert large["metric"] == "25000.00"


def test_small_ledgers_do_not_trigger_unusual_transaction(
    client: TestClient, db: Session, seeded: dict
) -> None:
    create_transaction(
        db,
        seeded["user_id"],
        seeded["account"],
        amount="25000",
        type_=TransactionType.EXPENSE,
        category=seeded["groceries"],
        occurred_on=today_utc(),
    )
    db.commit()

    report = client.get("/api/v1/insights", headers=seeded["headers"]).json()
    assert "large-transaction" not in _codes(report)


def test_no_goals_produces_a_nudge(client: TestClient, seeded: dict) -> None:
    report = client.get("/api/v1/insights", headers=seeded["headers"]).json()
    assert "no-goals" in _codes(report)

    client.post(
        "/api/v1/goals",
        headers=seeded["headers"],
        json={
            "name": "Emergency fund",
            "target_amount": "100000",
            "target_date": (today_utc() + dt.timedelta(days=200)).isoformat(),
        },
    )
    report = client.get("/api/v1/insights", headers=seeded["headers"]).json()
    assert "no-goals" not in _codes(report)
    assert any(code.startswith("goal-plan-") for code in _codes(report))


def test_recurring_load_warning(client: TestClient, seeded: dict) -> None:
    headers = seeded["headers"]
    client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "account_id": seeded["account_id"],
            "category_id": seeded["salary_id"],
            "amount": "50000",
            "type": "income",
            "description": "Salary",
            "occurred_on": today_utc().isoformat(),
        },
    )
    client.post(
        "/api/v1/recurring",
        headers=headers,
        json={
            "account_id": seeded["account_id"],
            "category_id": seeded["groceries_id"],
            "description": "Heavy subscription",
            "type": "expense",
            "amount": "20000",
            "frequency": "monthly",
            "next_run_on": (today_utc() + dt.timedelta(days=5)).isoformat(),
        },
    )

    report = client.get("/api/v1/insights", headers=headers).json()
    assert "recurring-load" in _codes(report)


def test_health_score_is_bounded_and_monotonic(
    client: TestClient, db: Session, seeded: dict
) -> None:
    """More savings must never lower the score."""
    from app.services.insights import InsightService

    service = InsightService(db)

    def score(rate: float) -> int:
        return service.health_score(rate, [])

    assert 0 <= score(-50) <= 100
    assert 0 <= score(0) <= 100
    assert score(5) < score(15) < score(25) < score(40)
    # Without budgets the budget half is capped at a neutral 20/40.
    assert score(1000) == 80
    assert score(30) == 80  # savings component maxes out at a 30% rate

    # With budgets, adherence is factored in.
    good_budget = type("B", (), {"is_over": False})()
    bad_budget = type("B", (), {"is_over": True})()
    assert service.health_score(20, [good_budget]) > service.health_score(20, [bad_budget])
    assert service.health_score(30, [good_budget]) == 100


def test_insight_categories_are_never_negative(client: TestClient, seeded: dict) -> None:
    """Regression guard: the concentration rule must not divide by zero."""
    report = client.get("/api/v1/insights", headers=seeded["headers"]).json()
    assert report["summary"]["total_expense"] == "0.00"
    assert report["summary"]["top_category"] is None
    assert all(insight["message"] for insight in report["insights"])


def test_category_concentration_insight(client: TestClient, db: Session, seeded: dict) -> None:
    category = create_category(db, seeded["user_id"], name="Travel", kind=CategoryKind.EXPENSE)
    create_transaction(
        db,
        seeded["user_id"],
        seeded["account"],
        amount="40000",
        type_=TransactionType.EXPENSE,
        category=category,
        occurred_on=today_utc(),
    )
    create_transaction(
        db,
        seeded["user_id"],
        seeded["account"],
        amount="1000",
        type_=TransactionType.EXPENSE,
        category=seeded["groceries"],
        occurred_on=today_utc(),
    )
    db.commit()

    report = client.get("/api/v1/insights", headers=seeded["headers"]).json()
    concentration = next(i for i in report["insights"] if i["code"] == "category-concentration")
    assert "Travel" in concentration["title"]
    assert report["summary"]["top_category"] == "Travel"
    assert report["summary"]["top_category_amount"] == "40000.00"


def test_credit_card_accounts_are_liabilities(
    client: TestClient, db: Session, seeded: dict
) -> None:
    card = create_account(
        db, seeded["user_id"], name="Card", type_=AccountType.CREDIT_CARD, opening_balance="0"
    )
    create_transaction(
        db,
        seeded["user_id"],
        card,
        amount="1000",
        type_=TransactionType.EXPENSE,
        category=seeded["groceries"],
        occurred_on=today_utc(),
    )
    db.commit()

    report = client.get("/api/v1/insights", headers=seeded["headers"]).json()
    assert report["summary"]["net"] == "-1000.00"
