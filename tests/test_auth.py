"""Authentication API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import TEST_PASSWORD


def test_register_returns_token_and_seeds_categories(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "Asha@Example.com", "password": TEST_PASSWORD, "full_name": "Asha"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["user"]["email"] == "asha@example.com"  # normalised
    assert body["user"]["currency"] == "INR"

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    categories = client.get("/api/v1/categories", headers=headers).json()
    assert len(categories) >= 12


def test_register_rejects_weak_or_duplicate(client: TestClient) -> None:
    payload = {"email": "dup@example.com", "password": TEST_PASSWORD}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201

    duplicate = client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "conflict"
    assert duplicate.headers["content-type"].startswith("application/problem+json")

    weak = client.post(
        "/api/v1/auth/register", json={"email": "weak@example.com", "password": "short"}
    )
    assert weak.status_code == 422
    assert weak.json()["code"] == "validation-error"
    assert weak.json()["errors"][0]["field"] == "password"

    malformed = client.post(
        "/api/v1/auth/register", json={"email": "not-an-email", "password": TEST_PASSWORD}
    )
    assert malformed.status_code == 422


def test_login_json_and_form_flows(client: TestClient, user: dict[str, object]) -> None:
    json_login = client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": TEST_PASSWORD},
    )
    assert json_login.status_code == 200
    assert json_login.json()["user"]["email"] == user["email"]

    form_login = client.post(
        "/api/v1/auth/token",
        data={"username": user["email"], "password": TEST_PASSWORD},
    )
    assert form_login.status_code == 200
    assert form_login.json()["access_token"]


def test_login_failures_are_indistinguishable(client: TestClient, user: dict[str, object]) -> None:
    wrong_password = client.post(
        "/api/v1/auth/login", json={"email": user["email"], "password": "wrong-password"}
    )
    unknown_email = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": TEST_PASSWORD}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


def test_protected_endpoints_require_a_token(client: TestClient) -> None:
    for path in ("/api/v1/accounts", "/api/v1/transactions", "/api/v1/dashboard"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["code"] == "unauthorized"


def test_bearer_token_with_bad_signature_is_rejected(client: TestClient, auth: dict) -> None:
    tampered = auth["Authorization"][:-4] + "aaaa"
    response = client.get("/api/v1/auth/me", headers={"Authorization": tampered})
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


def test_profile_update_and_password_change(client: TestClient, user: dict, auth: dict) -> None:
    updated = client.patch(
        "/api/v1/auth/me", headers=auth, json={"full_name": "New Name", "currency": "USD"}
    )
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "New Name"
    assert updated.json()["currency"] == "USD"

    bad = client.post(
        "/api/v1/auth/change-password",
        headers=auth,
        json={"current_password": "not-it", "new_password": "NewPass123!"},
    )
    assert bad.status_code == 401

    changed = client.post(
        "/api/v1/auth/change-password",
        headers=auth,
        json={"current_password": TEST_PASSWORD, "new_password": "NewPass123!"},
    )
    assert changed.status_code == 200

    assert (
        client.post(
            "/api/v1/auth/login", json={"email": user["email"], "password": TEST_PASSWORD}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": user["email"], "password": "NewPass123!"}
        ).status_code
        == 200
    )
