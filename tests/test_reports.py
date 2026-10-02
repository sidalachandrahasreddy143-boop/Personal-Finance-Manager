"""Reporting endpoints: the numbers must be exactly right."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import AccountType, TransactionType
from app.services.periods import add_months, month_start, previous_window, today_utc
from tests.conftest import create_account, create_transaction


def _populate(db: Session, seeded: dict) -> None:
    """Two full months of history: this month and last month."""
    user_id = seeded["user_id"]
    account = seeded["account"]
    groceries = seeded["groceries"]
    salary = seeded["salary"]

    this_month = month_start(today_utc())
    last_month = add_months(this_month, -1)

    create_transaction(
        db,
        user_id,
        account,
        amount="85000",
        type_=TransactionType.INCOME,
        category=salary,
        occurred_on=this_month,
        description="Salary",
    )
    create_transaction(
        db,
        user_id,
        account,
        amount="20000",
        type_=TransactionType.EXPENSE,
        category=groceries,
        occurred_on=this_month,
        description="Rent",
    )
    create_transaction(
        db,
        user_id,
        account,
        amount="5000",
        type_=TransactionType.EXPENSE,
        category=groceries,
        occurred_on=this_month + dt.timedelta(days=1),
        description="Groceries",
    )

    create_transaction(
        db,
        user_id,
        account,
        amount="80000",
        type_=TransactionType.INCOME,
        category=salary,
        occurred_on=last_month,
        description="Salary",
    )
    create_transaction(
        db,
        user_id,
        account,
        amount="10000",
        type_=TransactionType.EXPENSE,
        category=groceries,
        occurred_on=last_month,
        description="Rent",
    )
    db.commit()


def test_cashflow_totals_and_savings_rate(client: TestClient, db: Session, seeded: dict) -> None:
    _populate(db, seeded)
    headers = seeded["headers"]
    today = today_utc()

    response = client.get(
        f"/api/v1/reports/cashflow?from={month_start(today).isoformat()}&to={today.isoformat()}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["income_total"] == "85000.00"
    assert body["expense_total"] == "25000.00"
    assert body["net"] == "60000.00"
    assert body["savings_rate"] == 70.59
    assert body["granularity"] == "month"
    assert len(body["points"]) == 1
    assert body["points"][0]["period"] == today.strftime("%Y-%m")


def test_cashflow_includes_zero_filled_months(
    client: TestClient, db: Session, seeded: dict
) -> None:
    _populate(db, seeded)
    headers = seeded["headers"]
    start = add_months(month_start(today_utc()), -3)

    body = client.get(
        f"/api/v1/reports/cashflow?from={start.isoformat()}&to={today_utc().isoformat()}",
        headers=headers,
    ).json()

    periods = [point["period"] for point in body["points"]]
    assert len(periods) == 4  # three months back plus the current one
    empty_months = [p for p in body["points"] if p["income"] == "0.00" and p["expense"] == "0.00"]
    assert len(empty_months) == 2


def test_category_breakdown_shares_and_change(
    client: TestClient, db: Session, seeded: dict
) -> None:
    _populate(db, seeded)
    headers = seeded["headers"]
    start = add_months(month_start(today_utc()), -1)

    body = client.get(
        f"/api/v1/reports/categories?from={start.isoformat()}&to={today_utc().isoformat()}",
        headers=headers,
    ).json()

    assert body["kind"] == "expense"
    assert body["total"] == "35000.00"

    groceries = next(item for item in body["items"] if item["name"] == "Groceries")
    assert groceries["total"] == "35000.00"
    assert groceries["share_pct"] == 100.0
    assert groceries["transaction_count"] == 3
    assert groceries["previous_total"] == "0.00"
    assert groceries["average_amount"] == "11666.67"


def test_month_over_month_change_is_reported(client: TestClient, db: Session, seeded: dict) -> None:
    """`previous_total` compares against an equal-length window ending the day before."""
    today = today_utc()
    window_start = today - dt.timedelta(days=9)
    previous_start, previous_end = previous_window(window_start, today)

    create_transaction(
        db,
        seeded["user_id"],
        seeded["account"],
        amount="8000",
        type_=TransactionType.EXPENSE,
        category=seeded["groceries"],
        occurred_on=previous_end,
        description="Previous window spend",
    )
    create_transaction(
        db,
        seeded["user_id"],
        seeded["account"],
        amount="12000",
        type_=TransactionType.EXPENSE,
        category=seeded["groceries"],
        occurred_on=today,
        description="Current window spend",
    )
    db.commit()

    body = client.get(
        f"/api/v1/reports/categories?from={window_start.isoformat()}&to={today.isoformat()}",
        headers=seeded["headers"],
    ).json()

    groceries = next(item for item in body["items"] if item["name"] == "Groceries")
    assert groceries["total"] == "12000.00"
    assert groceries["previous_total"] == "8000.00"
    assert groceries["change_pct"] == 50.0
    assert previous_start < previous_end


def test_net_worth_splits_assets_and_liabilities(
    client: TestClient, db: Session, seeded: dict
) -> None:
    user_id = seeded["user_id"]
    card = create_account(
        db, user_id, name="Credit Card", type_=AccountType.CREDIT_CARD, opening_balance="0"
    )
    create_transaction(
        db,
        user_id,
        card,
        amount="15000",
        type_=TransactionType.EXPENSE,
        category=seeded["groceries"],
        description="Card spend",
    )
    db.commit()

    body = client.get("/api/v1/reports/net-worth", headers=seeded["headers"]).json()
    assert body["assets"] == "10000.00"  # the bank account's opening balance
    assert body["liabilities"] == "15000.00"  # the card's negative balance
    assert body["net_worth"] == "-5000.00"
    types = {row["type"]: row for row in body["by_type"]}
    assert types["credit_card"]["balance"] == "-15000.00"


def test_trends_are_gap_free_and_summarised(client: TestClient, db: Session, seeded: dict) -> None:
    _populate(db, seeded)
    body = client.get("/api/v1/reports/trends?months=6", headers=seeded["headers"]).json()

    assert len(body["months"]) == 6
    assert body["best_month"] is not None
    assert body["worst_month"] is not None
    assert float(body["average_monthly_income"]) > 0
    assert float(body["average_monthly_expense"]) > 0
    assert body["months"][0]["income"] == "0.00"  # gap-filled leading months


def test_top_transactions_and_merchants(client: TestClient, db: Session, seeded: dict) -> None:
    _populate(db, seeded)
    headers = seeded["headers"]

    last_month = add_months(month_start(today_utc()), -1)
    window = f"?from={last_month.isoformat()}&to={today_utc().isoformat()}"
    top = client.get(f"/api/v1/reports/top-transactions{window}&limit=2", headers=headers).json()
    assert [row["amount"] for row in top] == ["20000.00", "10000.00"]

    merchants = client.get(f"/api/v1/reports/merchants{window}", headers=headers).json()
    assert merchants == []  # none of the seeded rows has a merchant

    create_transaction(
        db,
        seeded["user_id"],
        seeded["account"],
        amount="999",
        type_=TransactionType.EXPENSE,
        category=seeded["groceries"],
        merchant="BigBasket",
        description="Order",
    )
    db.commit()
    merchants = client.get(f"/api/v1/reports/merchants{window}", headers=headers).json()
    assert merchants[0]["merchant"] == "BigBasket"
    assert merchants[0]["total"] == "999.00"


def test_dashboard_aggregates_everything(client: TestClient, db: Session, seeded: dict) -> None:
    _populate(db, seeded)
    body = client.get("/api/v1/dashboard", headers=seeded["headers"]).json()

    for key in (
        "as_of",
        "month",
        "cashflow",
        "categories",
        "net_worth",
        "trends",
        "budgets",
        "insights",
        "recent_transactions",
    ):
        assert key in body, key

    assert body["month"]["income"] == "85000.00"
    assert body["month"]["expense"] == "25000.00"
    assert body["recent_transactions"][0]["description"] in {"Salary", "Groceries", "Rent"}
    assert 0 <= body["insights"]["summary"]["health_score"] <= 100


def test_empty_ledger_reports_do_not_crash(client: TestClient, seeded: dict) -> None:
    headers = seeded["headers"]
    for path in (
        "/api/v1/reports/cashflow",
        "/api/v1/reports/categories",
        "/api/v1/reports/net-worth",
        "/api/v1/reports/trends",
        "/api/v1/reports/top-transactions",
        "/api/v1/reports/merchants",
        "/api/v1/insights",
        "/api/v1/dashboard",
    ):
        response = client.get(path, headers=headers)
        assert response.status_code == 200, (path, response.text)
