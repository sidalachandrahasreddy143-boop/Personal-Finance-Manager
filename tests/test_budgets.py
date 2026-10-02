"""Budget endpoints and utilisation maths."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import CategoryKind, TransactionType
from app.services.periods import month_start, today_utc
from tests.conftest import create_budget, create_category, create_transaction


def test_create_budget_and_status_maths(client: TestClient, seeded: dict) -> None:
    headers = seeded["headers"]
    start = month_start(today_utc())

    created = client.post(
        "/api/v1/budgets",
        headers=headers,
        json={"category_id": seeded["groceries_id"], "amount_limit": "10000", "period": "monthly"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["period_start"] == start.isoformat()
    assert created.json()["alert_threshold"] == 0.8

    # spend 4,000 of the 10,000 envelope
    for amount in ("1500", "2500"):
        response = client.post(
            "/api/v1/transactions",
            headers=headers,
            json={
                "account_id": seeded["account_id"],
                "category_id": seeded["groceries_id"],
                "amount": amount,
                "type": "expense",
                "description": "Groceries",
                "occurred_on": today_utc().isoformat(),
            },
        )
        assert response.status_code == 201

    status = client.get("/api/v1/budgets", headers=headers).json()[0]
    assert status["spent"] == "4000.00"
    assert status["remaining"] == "6000.00"
    assert status["used_pct"] == 40.0
    assert status["is_over"] is False
    assert status["is_alert"] is False
    assert status["days_remaining"] >= 0
    assert float(status["safe_daily_spend"]) > 0
    assert float(status["projected_spend"]) >= 4000.0


def test_budget_flags_over_and_alert(client: TestClient, seeded: dict) -> None:
    headers = seeded["headers"]
    client.post(
        "/api/v1/budgets",
        headers=headers,
        json={"category_id": seeded["groceries_id"], "amount_limit": "1000"},
    )
    client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "account_id": seeded["account_id"],
            "category_id": seeded["groceries_id"],
            "amount": "1500",
            "type": "expense",
            "description": "Overspend",
            "occurred_on": today_utc().isoformat(),
        },
    )

    status = client.get("/api/v1/budgets", headers=headers).json()[0]
    assert status["is_over"] is True
    assert status["is_alert"] is True
    assert status["remaining"] == "-500.00"
    assert status["safe_daily_spend"] == "0.00"


def test_duplicate_envelope_is_rejected(client: TestClient, seeded: dict) -> None:
    headers = seeded["headers"]
    payload = {"category_id": seeded["groceries_id"], "amount_limit": "5000"}

    assert client.post("/api/v1/budgets", headers=headers, json=payload).status_code == 201
    duplicate = client.post("/api/v1/budgets", headers=headers, json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "conflict"


def test_income_category_cannot_be_budgeted(client: TestClient, seeded: dict) -> None:
    response = client.post(
        "/api/v1/budgets",
        headers=seeded["headers"],
        json={"category_id": seeded["salary_id"], "amount_limit": "5000"},
    )
    assert response.status_code == 422
    assert "income category" in response.json()["detail"]


def test_rollover_adds_last_periods_unspent_amount(
    client: TestClient, db: Session, seeded: dict
) -> None:
    user_id = seeded["user_id"]
    this_month = month_start(today_utc())
    last_month = month_start(this_month - dt.timedelta(days=1))

    # last month: 6,000 spent of a 10,000 envelope => 4,000 rolls over
    create_transaction(
        db,
        user_id,
        seeded["account"],
        amount="6000",
        type_=TransactionType.EXPENSE,
        category=seeded["groceries"],
        occurred_on=last_month + dt.timedelta(days=2),
    )
    db.commit()

    client.post(
        "/api/v1/budgets",
        headers=seeded["headers"],
        json={
            "category_id": seeded["groceries_id"],
            "amount_limit": "10000",
            "rollover": True,
            "period_start": this_month.isoformat(),
        },
    )

    status = client.get("/api/v1/budgets", headers=seeded["headers"]).json()[0]
    assert status["budget"]["rollover"] is True
    assert status["spent"] == "0.00"
    # effective limit = 10,000 + 4,000 rollover
    assert status["remaining"] == "14000.00"


def test_budget_update_and_delete(client: TestClient, db: Session, seeded: dict) -> None:
    headers = seeded["headers"]
    budget = create_budget(db, seeded["user_id"], seeded["groceries"], limit="3000")
    db.commit()

    updated = client.patch(
        f"/api/v1/budgets/{budget.id}", headers=headers, json={"amount_limit": "4500"}
    )
    assert updated.status_code == 200
    assert updated.json()["amount_limit"] == "4500.00"

    assert client.delete(f"/api/v1/budgets/{budget.id}", headers=headers).status_code == 200
    assert client.get("/api/v1/budgets", headers=headers).json() == []


def test_budgets_are_isolated_between_users(client: TestClient, seeded: dict) -> None:
    other = client.post(
        "/api/v1/auth/register",
        json={"email": "budget-other@example.com", "password": "Str0ng-pass!"},
    ).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}

    created = client.post(
        "/api/v1/budgets",
        headers=other_headers,
        json={"category_id": seeded["groceries_id"], "amount_limit": "1000"},
    )
    assert created.status_code == 404  # category belongs to someone else


def test_weekly_period_window_is_normalised(client: TestClient, db: Session, seeded: dict) -> None:
    headers = seeded["headers"]
    category = create_category(db, seeded["user_id"], name="Coffee", kind=CategoryKind.EXPENSE)
    db.commit()

    response = client.post(
        "/api/v1/budgets",
        headers=headers,
        json={"category_id": category.id, "amount_limit": "2000", "period": "weekly"},
    )
    assert response.status_code == 201
    start = dt.date.fromisoformat(response.json()["period_start"])
    assert start.weekday() == 0  # Monday
