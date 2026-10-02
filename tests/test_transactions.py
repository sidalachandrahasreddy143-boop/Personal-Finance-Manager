"""Transaction endpoints: validation, filtering, pagination and business rules."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from app.services.periods import today_utc


def _payload(seeded: dict, **overrides: object) -> dict:
    payload = {
        "account_id": seeded["account_id"],
        "category_id": seeded["groceries_id"],
        "amount": "750.25",
        "type": "expense",
        "description": "Weekly groceries",
        "merchant": "BigBasket",
        "occurred_on": today_utc().isoformat(),
        "tags": ["Groceries", "weekly"],
    }
    payload.update(overrides)
    return payload


def test_create_read_update_delete(client: TestClient, seeded: dict) -> None:
    auth = seeded["headers"]
    created = client.post("/api/v1/transactions", headers=auth, json=_payload(seeded))
    assert created.status_code == 201, created.text
    txn = created.json()
    assert txn["amount"] == "750.25"
    assert txn["currency"] == "INR"  # inherited from the account
    assert txn["tags"] == ["groceries", "weekly"]  # normalised: lowercase + sorted

    fetched = client.get(f"/api/v1/transactions/{txn['id']}", headers=auth).json()
    assert fetched["description"] == "Weekly groceries"

    updated = client.patch(
        f"/api/v1/transactions/{txn['id']}",
        headers=auth,
        json={"amount": "900.00", "notes": "Corrected from receipt"},
    )
    assert updated.status_code == 200
    assert updated.json()["amount"] == "900.00"
    assert updated.json()["notes"] == "Corrected from receipt"
    assert updated.json()["description"] == "Weekly groceries"  # unchanged

    assert client.delete(f"/api/v1/transactions/{txn['id']}", headers=auth).status_code == 200
    assert client.get(f"/api/v1/transactions/{txn['id']}", headers=auth).status_code == 404


def test_amount_must_be_positive_and_decimal(client: TestClient, seeded: dict) -> None:
    auth = seeded["headers"]
    negative = client.post(
        "/api/v1/transactions", headers=auth, json=_payload(seeded, amount="-10")
    )
    assert negative.status_code == 422

    zero = client.post("/api/v1/transactions", headers=auth, json=_payload(seeded, amount="0"))
    assert zero.status_code == 422

    too_precise = client.post(
        "/api/v1/transactions", headers=auth, json=_payload(seeded, amount="10.999")
    )
    assert too_precise.status_code == 422


def test_category_kind_must_match_transaction_type(client: TestClient, seeded: dict) -> None:
    auth = seeded["headers"]
    mismatched = client.post(
        "/api/v1/transactions",
        headers=auth,
        json=_payload(seeded, type="income", category_id=seeded["groceries_id"]),
    )
    assert mismatched.status_code == 422
    assert mismatched.json()["code"] == "business-rule"
    assert "expense category" in mismatched.json()["detail"]

    # flipping the type of an existing transaction is caught as well
    created = client.post("/api/v1/transactions", headers=auth, json=_payload(seeded)).json()
    flipped = client.patch(
        f"/api/v1/transactions/{created['id']}", headers=auth, json={"type": "income"}
    )
    assert flipped.status_code == 422

    # ...unless a matching category is supplied in the same request
    ok = client.patch(
        f"/api/v1/transactions/{created['id']}",
        headers=auth,
        json={"type": "income", "category_id": seeded["salary_id"]},
    )
    assert ok.status_code == 200
    assert ok.json()["type"] == "income"
    assert ok.json()["category_id"] == seeded["salary_id"]


def test_archived_category_cannot_be_used(client: TestClient, seeded: dict) -> None:
    auth = seeded["headers"]
    client.patch(
        f"/api/v1/categories/{seeded['groceries_id']}", headers=auth, json={"is_archived": True}
    )
    response = client.post("/api/v1/transactions", headers=auth, json=_payload(seeded))
    assert response.status_code == 422
    assert "archived" in response.json()["detail"]


def test_filters_compose(client: TestClient, seeded: dict) -> None:
    auth = seeded["headers"]
    today = today_utc()
    rows = [
        ("500", "expense", "BigBasket groceries", "BigBasket", today),
        ("2500", "expense", "Amazon order", "Amazon", today - dt.timedelta(days=40)),
        ("4200", "expense", "Dinner party", "Truffles", today - dt.timedelta(days=5)),
        ("85000", "income", "Monthly salary", "Acme Corp", today - dt.timedelta(days=2)),
    ]
    for amount, kind, description, merchant, when in rows:
        category = seeded["salary_id"] if kind == "income" else seeded["groceries_id"]
        response = client.post(
            "/api/v1/transactions",
            headers=auth,
            json=_payload(
                seeded,
                amount=amount,
                type=kind,
                description=description,
                merchant=merchant,
                category_id=category,
                occurred_on=when.isoformat(),
            ),
        )
        assert response.status_code == 201, response.text

    def total(query: str = "") -> int:
        return client.get(f"/api/v1/transactions{query}", headers=auth).json()["total"]

    assert total() == 4
    assert total("?type=income") == 1
    assert total("?type=expense") == 3
    assert total("?search=amazon") == 1
    assert total("?search=truffles") == 1
    assert total(f"?category_id={seeded['groceries_id']}") == 3
    assert total("?min_amount=2000") == 3
    assert total("?max_amount=2000") == 1
    assert total(f"?from={today.isoformat()}") == 1
    assert total(f"?to={(today - dt.timedelta(days=10)).isoformat()}") == 1
    assert total("?tag=weekly") == 4

    sorted_desc = client.get("/api/v1/transactions?sort=amount&order=desc", headers=auth).json()
    assert sorted_desc["items"][0]["amount"] == "85000.00"
    sorted_asc = client.get("/api/v1/transactions?sort=amount&order=asc", headers=auth).json()
    assert sorted_asc["items"][0]["amount"] == "500.00"


def test_pagination_metadata(client: TestClient, seeded: dict) -> None:
    auth = seeded["headers"]
    for index in range(7):
        client.post(
            "/api/v1/transactions",
            headers=auth,
            json=_payload(seeded, description=f"Row {index}", amount=f"{100 + index}.00"),
        )

    first = client.get("/api/v1/transactions?page=1&size=3", headers=auth).json()
    assert first["total"] == 7
    assert first["pages"] == 3
    assert len(first["items"]) == 3

    last = client.get("/api/v1/transactions?page=3&size=3", headers=auth).json()
    assert len(last["items"]) == 1

    beyond = client.get("/api/v1/transactions?page=99&size=3", headers=auth).json()
    assert beyond["items"] == []
    assert beyond["total"] == 7

    invalid = client.get("/api/v1/transactions?size=1000", headers=auth)
    assert invalid.status_code == 422


def test_suggest_category_endpoint(client: TestClient, auth: dict) -> None:
    response = client.get(
        "/api/v1/transactions/suggest-category",
        headers=auth,
        params={"description": "Swiggy dinner with friends"},
    )
    assert response.status_code == 200
    assert response.json()["suggested_category"] == "Dining"
    assert 0 < response.json()["confidence"] <= 1

    unknown = client.get(
        "/api/v1/transactions/suggest-category", headers=auth, params={"description": "qwerty"}
    ).json()
    assert unknown["suggested_category"] is None
    assert unknown["confidence"] == 0.0
