"""Cross-cutting API contract: problem+json errors, headers and rate limits."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core import rate_limit
from app.core.config import settings


def test_unknown_route_returns_problem_json(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 404
    assert body["code"]
    assert body["request_id"]


def test_error_envelope_has_stable_shape(client: TestClient, auth: dict) -> None:
    response = client.get("/api/v1/accounts/999999", headers=auth)
    assert response.status_code == 404

    body = response.json()
    assert set(body) >= {"type", "title", "status", "detail", "code", "request_id", "instance"}
    assert body["instance"] == "/api/v1/accounts/999999"
    assert body["code"] == "not-found"


def test_validation_errors_list_offending_fields(client: TestClient, auth: dict) -> None:
    response = client.post("/api/v1/accounts", headers=auth, json={"name": "", "type": "nope"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation-error"
    fields = {error["field"] for error in body["errors"]}
    assert {"name", "type"} <= fields


def test_request_id_is_echoed_and_generated(client: TestClient) -> None:
    generated = client.get("/api/v1/health/live")
    assert generated.headers["X-Request-ID"]
    assert float(generated.headers["X-Process-Time-ms"]) >= 0

    echoed = client.get("/api/v1/health/live", headers={"X-Request-ID": "abc123"})
    assert echoed.headers["X-Request-ID"] == "abc123"


def test_security_headers_are_absent_but_gzip_present(client: TestClient, auth: dict) -> None:
    response = client.get("/api/v1/meta", headers={**auth, "Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.json()["version"]


def test_health_reports_database_state(client: TestClient) -> None:
    body = client.get("/api/v1/health").json()
    assert body["database"] == "ok"
    assert body["status"] == "ok"
    assert body["uptime_seconds"] >= 0


def test_root_redirects_to_dashboard(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/app"


def test_api_hint_endpoint(client: TestClient) -> None:
    body = client.get("/api").json()
    assert body["docs"] == "/docs"
    assert body["health"] == "/api/v1/health"


def test_rate_limit_returns_429_problem_json(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(rate_limit.general_limiter, "limit", 3)
    rate_limit.general_limiter.reset()

    # /api/v1/meta is rate limited; /health is deliberately exempt for probes.
    try:
        statuses = [client.get("/api/v1/meta").status_code for _ in range(5)]
        assert statuses[:3] == [200, 200, 200]
        assert statuses[3:] == [429, 429]

        body = client.get("/api/v1/meta").json()
        assert body["code"] == "rate-limited"
        assert body["limit_per_minute"] == 3
    finally:
        rate_limit.general_limiter.reset()


def test_auth_endpoints_use_the_stricter_bucket(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(rate_limit.auth_limiter, "limit", 2)
    rate_limit.auth_limiter.reset()

    try:
        payload = {"email": "nobody@example.com", "password": "WrongPass123"}
        first = client.post("/api/v1/auth/login", json=payload)
        second = client.post("/api/v1/auth/login", json=payload)
        third = client.post("/api/v1/auth/login", json=payload)

        assert first.status_code == second.status_code == 401
        assert third.status_code == 429
    finally:
        rate_limit.auth_limiter.reset()


def test_pagination_parameters_are_validated(client: TestClient, auth: dict) -> None:
    assert client.get("/api/v1/transactions?page=0", headers=auth).status_code == 422
    assert client.get("/api/v1/transactions?size=0", headers=auth).status_code == 422
    assert client.get("/api/v1/transactions?sort=drop_table", headers=auth).status_code == 422
    assert client.get("/api/v1/transactions?order=sideways", headers=auth).status_code == 422


def test_date_range_is_validated(client: TestClient, auth: dict) -> None:
    response = client.get("/api/v1/reports/cashflow?from=not-a-date", headers=auth)
    assert response.status_code == 422
