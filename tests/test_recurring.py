"""Recurring rule endpoints and the materialisation engine."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.periods import today_utc


def _rule_payload(seeded: dict, **overrides: object) -> dict:
    payload = {
        "account_id": seeded["account_id"],
        "category_id": seeded["salary_id"],
        "description": "Monthly salary",
        "merchant": "Acme Corp",
        "type": "income",
        "amount": "85000",
        "frequency": "monthly",
        "next_run_on": today_utc().isoformat(),
    }
    payload.update(overrides)
    return payload


def test_create_and_list_rules(client: TestClient, seeded: dict) -> None:
    headers = seeded["headers"]
    created = client.post("/api/v1/recurring", headers=headers, json=_rule_payload(seeded))
    assert created.status_code == 201, created.text
    assert created.json()["frequency"] == "monthly"
    assert created.json()["is_active"] is True

    listed = client.get("/api/v1/recurring", headers=headers).json()
    assert len(listed) == 1

    assert (
        client.patch(
            f"/api/v1/recurring/{created.json()['id']}", headers=headers, json={"is_active": False}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/recurring", headers=headers).json() == []
    assert len(client.get("/api/v1/recurring?include_inactive=true", headers=headers).json()) == 1


def test_end_date_must_not_precede_next_run(client: TestClient, seeded: dict) -> None:
    response = client.post(
        "/api/v1/recurring",
        headers=seeded["headers"],
        json=_rule_payload(
            seeded,
            next_run_on=today_utc().isoformat(),
            end_date=(today_utc() - dt.timedelta(days=1)).isoformat(),
        ),
    )
    assert response.status_code == 422
    assert "end_date" in response.json()["detail"]


def test_run_posts_due_transactions_and_is_idempotent(client: TestClient, seeded: dict) -> None:
    headers = seeded["headers"]
    start = today_utc() - dt.timedelta(days=70)  # ~3 monthly runs are due

    client.post(
        "/api/v1/recurring",
        headers=headers,
        json=_rule_payload(seeded, next_run_on=start.isoformat(), frequency="monthly", interval=1),
    )

    first = client.post("/api/v1/recurring/run", headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["posted"] == 3
    posted_dates = [t["occurred_on"] for t in body["transactions"]]
    assert posted_dates == sorted(posted_dates)
    assert posted_dates[0] == start.isoformat()
    assert all(t["is_recurring"] for t in body["transactions"])

    # Nothing is due any more -> running again posts nothing.
    second = client.post("/api/v1/recurring/run", headers=headers)
    assert second.json()["posted"] == 0

    ledger = client.get("/api/v1/transactions?type=income", headers=headers).json()
    assert ledger["total"] == 3
    assert ledger["items"][0]["amount"] == "85000.00"


def test_rule_deactivates_after_end_date(client: TestClient, seeded: dict) -> None:
    headers = seeded["headers"]
    client.post(
        "/api/v1/recurring",
        headers=headers,
        json=_rule_payload(
            seeded,
            next_run_on=(today_utc() - dt.timedelta(days=40)).isoformat(),
            end_date=today_utc().isoformat(),
            frequency="weekly",
        ),
    )

    result = client.post("/api/v1/recurring/run", headers=headers).json()
    assert result["posted"] >= 5
    assert result["next_runs"] == []  # rule finished and was deactivated


def test_daily_rule_catch_up_is_capped(client: TestClient, seeded: dict) -> None:
    """A rule left dormant for years must not post thousands of rows."""
    headers = seeded["headers"]
    client.post(
        "/api/v1/recurring",
        headers=headers,
        json=_rule_payload(
            seeded,
            type="expense",
            category_id=seeded["groceries_id"],
            amount="100",
            frequency="daily",
            next_run_on=(today_utc() - dt.timedelta(days=400)).isoformat(),
        ),
    )

    result = client.post("/api/v1/recurring/run", headers=headers).json()
    assert result["posted"] <= 120  # MAX_CATCHUP_ITERATIONS


def test_future_rule_posts_nothing(client: TestClient, seeded: dict) -> None:
    headers = seeded["headers"]
    client.post(
        "/api/v1/recurring",
        headers=headers,
        json=_rule_payload(seeded, next_run_on=(today_utc() + dt.timedelta(days=10)).isoformat()),
    )
    assert client.post("/api/v1/recurring/run", headers=headers).json()["posted"] == 0


def test_worker_script_posts_for_every_user(client: TestClient, db: Session, seeded: dict) -> None:
    """The cron entry point behaves like the endpoint."""
    from app.scripts.run_recurring import run

    headers = seeded["headers"]
    client.post(
        "/api/v1/recurring",
        headers=headers,
        json=_rule_payload(seeded, next_run_on=today_utc().isoformat()),
    )

    posted = run(today_utc())
    assert posted == 1
    assert run(today_utc()) == 0
