"""Account endpoints: CRUD, balances and ownership isolation."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import AccountType, TransactionType
from app.services.periods import today_utc
from tests.conftest import create_transaction


def test_accounts_crud(client: TestClient, auth: dict) -> None:
    created = client.post(
        "/api/v1/accounts",
        headers=auth,
        json={
            "name": "ICICI Savings",
            "type": "bank",
            "opening_balance": "25000.50",
            "institution": "ICICI",
        },
    )
    assert created.status_code == 201, created.text
    account = created.json()
    assert account["opening_balance"] == "25000.50"
    account_id = account["id"]

    listed = client.get("/api/v1/accounts", headers=auth).json()
    assert [a["name"] for a in listed] == ["ICICI Savings"]

    patched = client.patch(
        f"/api/v1/accounts/{account_id}", headers=auth, json={"name": "ICICI Salary"}
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "ICICI Salary"
    assert patched.json()["opening_balance"] == "25000.50"  # untouched

    deleted = client.delete(f"/api/v1/accounts/{account_id}", headers=auth)
    assert deleted.status_code == 200
    assert client.get("/api/v1/accounts", headers=auth).json() == []


def test_duplicate_account_name_is_rejected(client: TestClient, auth: dict) -> None:
    payload = {"name": "Cash", "type": "cash"}
    assert client.post("/api/v1/accounts", headers=auth, json=payload).status_code == 201

    duplicate = client.post("/api/v1/accounts", headers=auth, json=payload)
    assert duplicate.status_code == 409
    assert "already have an account" in duplicate.json()["detail"]

    case_variant = client.post(
        "/api/v1/accounts", headers=auth, json={"name": "cash", "type": "cash"}
    )
    assert case_variant.status_code == 409


def test_balance_is_opening_plus_income_minus_expense(
    client: TestClient, db: Session, seeded: dict
) -> None:
    auth = seeded["headers"]
    user_id = seeded["user_id"]
    account = seeded["account"]

    create_transaction(
        db,
        user_id,
        account,
        amount="5000",
        type_=TransactionType.INCOME,
        category=seeded["salary"],
        description="Salary",
    )
    create_transaction(
        db,
        user_id,
        account,
        amount="1200",
        type_=TransactionType.EXPENSE,
        category=seeded["groceries"],
        description="Groceries",
    )
    db.commit()

    balances = client.get("/api/v1/accounts/balances", headers=auth).json()
    assert len(balances) == 1
    row = balances[0]
    assert row["current_balance"] == "13800.00"  # 10,000 opening + 5,000 - 1,200
    assert row["income_total"] == "5000.00"
    assert row["expense_total"] == "1200.00"
    assert row["transaction_count"] == 2


def test_archived_accounts_are_hidden_unless_requested(client: TestClient, auth: dict) -> None:
    account_id = client.post(
        "/api/v1/accounts", headers=auth, json={"name": "Old Wallet", "type": "wallet"}
    ).json()["id"]

    client.patch(f"/api/v1/accounts/{account_id}", headers=auth, json={"is_archived": True})

    assert client.get("/api/v1/accounts", headers=auth).json() == []
    archived = client.get("/api/v1/accounts?include_archived=true", headers=auth).json()
    assert len(archived) == 1


def test_delete_is_blocked_while_transactions_exist(
    client: TestClient, db: Session, seeded: dict
) -> None:
    auth = seeded["headers"]
    account = seeded["account"]
    create_transaction(db, seeded["user_id"], account, description="Keeps the account alive")
    db.commit()

    response = client.delete(f"/api/v1/accounts/{account.id}", headers=auth)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "business-rule"
    assert body["transaction_count"] == 1


def test_accounts_are_scoped_to_the_owner(client: TestClient, auth: dict, db: Session) -> None:
    other = client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": "Str0ng-pass!"},
    ).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}

    victim_account = client.post(
        "/api/v1/accounts", headers=other_headers, json={"name": "Victim Bank", "type": "bank"}
    ).json()

    assert client.get(f"/api/v1/accounts/{victim_account['id']}", headers=auth).status_code == 404
    assert (
        client.patch(
            f"/api/v1/accounts/{victim_account['id']}", headers=auth, json={"name": "Hacked"}
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/accounts/{victim_account['id']}", headers=auth).status_code == 404
    )

    # A transaction referencing someone else's account is refused too.
    denied = client.post(
        "/api/v1/transactions",
        headers=auth,
        json={
            "account_id": victim_account["id"],
            "amount": "10",
            "type": "expense",
            "description": "nope",
            "occurred_on": today_utc().isoformat(),
        },
    )
    assert denied.status_code == 404


def test_account_type_enum_is_validated(client: TestClient, auth: dict) -> None:
    response = client.post(
        "/api/v1/accounts", headers=auth, json={"name": "Weird", "type": "crypto-moon"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation-error"


def test_negative_opening_balance_is_allowed_only_for_liability_types(
    client: TestClient, auth: dict
) -> None:
    response = client.post(
        "/api/v1/accounts",
        headers=auth,
        json={"name": "Card", "type": AccountType.CREDIT_CARD.value, "opening_balance": "-1500"},
    )
    assert response.status_code == 422  # MoneyNonNegative rejects it
