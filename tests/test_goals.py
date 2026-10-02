"""Savings goal endpoints."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient


def test_goal_lifecycle_and_auto_achievement(client: TestClient, seeded: dict) -> None:
    headers = seeded["headers"]

    created = client.post(
        "/api/v1/goals",
        headers=headers,
        json={
            "name": "Emergency fund",
            "target_amount": "100000",
            "saved_amount": "25000",
            "target_date": (dt.date.today() + dt.timedelta(days=180)).isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    goal = created.json()
    assert goal["progress_pct"] == 25.0
    assert goal["status"] == "active"

    partial = client.post(
        f"/api/v1/goals/{goal['id']}/contributions", headers=headers, json={"amount": "15000"}
    )
    assert partial.status_code == 200
    assert partial.json()["saved_amount"] == "40000.00"
    assert partial.json()["status"] == "active"

    completed = client.post(
        f"/api/v1/goals/{goal['id']}/contributions", headers=headers, json={"amount": "60000"}
    )
    assert completed.json()["status"] == "achieved"
    assert completed.json()["progress_pct"] == 100.0

    # archived goals cannot receive money
    archived = client.patch(
        f"/api/v1/goals/{goal['id']}", headers=headers, json={"status": "archived"}
    )
    assert archived.status_code == 200
    rejected = client.post(
        f"/api/v1/goals/{goal['id']}/contributions", headers=headers, json={"amount": "100"}
    )
    assert rejected.status_code == 422

    assert client.delete(f"/api/v1/goals/{goal['id']}", headers=headers).status_code == 200
    assert client.get("/api/v1/goals", headers=headers).json() == []


def test_goal_validation_and_filtering(client: TestClient, seeded: dict) -> None:
    headers = seeded["headers"]

    bad_target = client.post(
        "/api/v1/goals", headers=headers, json={"name": "Zero", "target_amount": "0"}
    )
    assert bad_target.status_code == 422

    client.post("/api/v1/goals", headers=headers, json={"name": "Active", "target_amount": "5000"})
    done = client.post(
        "/api/v1/goals",
        headers=headers,
        json={"name": "Done", "target_amount": "5000", "saved_amount": "5000"},
    )
    assert done.json()["status"] == "achieved"

    active_only = client.get("/api/v1/goals?status=active", headers=headers).json()
    assert [goal["name"] for goal in active_only] == ["Active"]

    achieved_only = client.get("/api/v1/goals?status=achieved", headers=headers).json()
    assert [goal["name"] for goal in achieved_only] == ["Done"]


def test_goals_are_private(client: TestClient, seeded: dict) -> None:
    other = client.post(
        "/api/v1/auth/register",
        json={"email": "goal-other@example.com", "password": "Str0ng-pass!"},
    ).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}

    goal = client.post(
        "/api/v1/goals", headers=other_headers, json={"name": "Theirs", "target_amount": "1000"}
    ).json()

    assert client.get(f"/api/v1/goals/{goal['id']}", headers=seeded["headers"]).status_code == 404
    assert (
        client.post(
            f"/api/v1/goals/{goal['id']}/contributions",
            headers=seeded["headers"],
            json={"amount": "100"},
        ).status_code
        == 404
    )
