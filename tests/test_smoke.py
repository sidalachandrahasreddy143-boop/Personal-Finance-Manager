"""End-to-end smoke test: the whole happy path in one place.

If this file fails, nothing else in the suite matters.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from app.services.periods import today_utc


def test_health_and_meta(client: TestClient) -> None:
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"

    meta = client.get("/api/v1/meta")
    assert meta.status_code == 200
    assert meta.json()["api_prefix"] == "/api/v1"
    assert meta.json()["features"]["csv_import"] is True


def test_openapi_schema_is_valid(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"]
    assert "/api/v1/transactions" in schema["paths"]
    # every operation is documented
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            assert operation.get("summary"), f"{method.upper()} {path} is missing a summary"


def test_full_user_journey(client: TestClient) -> None:
    """Register -> bank account -> transaction -> budget -> dashboard -> insights."""
    register = client.post(
        "/api/v1/auth/register",
        json={
            "email": "journey@example.com",
            "password": "Str0ng-pass!",
            "full_name": "Journey User",
            "currency": "INR",
        },
    )
    assert register.status_code == 201, register.text
    token = register.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # registration seeds the starter categories
    categories = client.get("/api/v1/categories", headers=headers).json()
    names = {c["name"] for c in categories}
    assert {"Salary", "Groceries", "Rent"} <= names
    expense_category = next(c for c in categories if c["name"] == "Groceries")

    account = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"name": "HDFC Savings", "type": "bank", "opening_balance": "50000"},
    )
    assert account.status_code == 201, account.text
    account_id = account.json()["id"]
    assert account.json()["opening_balance"] == "50000.00"

    txn = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "account_id": account_id,
            "category_id": expense_category["id"],
            "amount": "1250.50",
            "type": "expense",
            "description": "Weekly groceries",
            "merchant": "BigBasket",
            "occurred_on": today_utc().isoformat(),
            "tags": ["groceries", "weekly"],
        },
    )
    assert txn.status_code == 201, txn.text
    assert txn.json()["amount"] == "1250.50"
    assert txn.json()["tags"] == ["groceries", "weekly"]

    budget = client.post(
        "/api/v1/budgets",
        headers=headers,
        json={"category_id": expense_category["id"], "amount_limit": "5000", "period": "monthly"},
    )
    assert budget.status_code == 201, budget.text
    assert budget.json()["amount_limit"] == "5000.00"

    statuses = client.get("/api/v1/budgets", headers=headers).json()
    assert len(statuses) == 1
    assert statuses[0]["spent"] == "1250.50"
    assert statuses[0]["remaining"] == "3749.50"
    assert 0 < statuses[0]["used_pct"] < 100

    balances = client.get("/api/v1/accounts/balances", headers=headers).json()
    assert balances[0]["current_balance"] == "48749.50"

    dashboard = client.get("/api/v1/dashboard", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    payload = dashboard.json()
    assert payload["month"]["expense"] == "1250.50"
    assert len(payload["recent_transactions"]) == 1
    assert payload["net_worth"]["assets"] == "48749.50"

    insights = client.get("/api/v1/insights", headers=headers).json()
    assert "health_score" in insights["summary"]
    assert isinstance(insights["insights"], list)

    export = client.get("/api/v1/data/export/transactions.csv", headers=headers)
    assert export.status_code == 200
    assert "Weekly groceries" in export.text


def test_csv_import_round_trip(client: TestClient, auth: dict[str, str]) -> None:
    """Bank-style CSV: existing categories are reused, unknown ones are created."""
    csv_content = (
        "date,description,amount,type,category,account,merchant,tags\n"
        f"{today_utc().isoformat()},BigBasket order,-2450,expense,Groceries,HDFC Savings,BigBasket,groceries\n"
        f"{(today_utc() - dt.timedelta(days=3)).isoformat()},September salary,85000,income,Salary,HDFC Savings,Acme Corp,salary\n"
        f"{(today_utc() - dt.timedelta(days=5)).isoformat()},Vet visit,-1800,expense,Pet Care,HDFC Savings,Pet Clinic,\n"
    )
    import_response = client.post(
        "/api/v1/data/import/csv",
        headers=auth,
        files={"file": ("statement.csv", csv_content, "text/csv")},
    )
    assert import_response.status_code == 200, import_response.text
    summary = import_response.json()

    assert summary["imported"] == 3
    assert summary["skipped"] == 0
    assert summary["total_rows"] == 3
    assert summary["created_accounts"] == ["HDFC Savings"]
    # 'Groceries' and 'Salary' already exist from the registration seed set.
    assert summary["created_categories"] == ["Pet Care"]

    listed = client.get("/api/v1/transactions", headers=auth).json()
    assert listed["total"] == 3
    assert {item["type"] for item in listed["items"]} == {"income", "expense"}


def test_csv_import_reports_bad_rows_and_supports_dry_run(
    client: TestClient, auth: dict[str, str]
) -> None:
    csv_content = (
        "date,description,amount\n"
        f"{today_utc().isoformat()},Good row,-100\n"
        "31/12/not-a-date,Broken date,-200\n"
        f"{today_utc().isoformat()},Bad amount,abc\n"
    )
    response = client.post(
        "/api/v1/data/import/csv?dry_run=true",
        headers=auth,
        files={"file": ("statement.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["dry_run"] is True
    assert summary["imported"] == 1
    assert summary["skipped"] == 2
    assert {error["row"] for error in summary["errors"]} == {3, 4}

    # Nothing was persisted by the dry run.
    assert client.get("/api/v1/transactions", headers=auth).json()["total"] == 0
