"""Shared OpenAPI metadata: tags, descriptions and reusable error responses."""

from __future__ import annotations

from typing import Any

from app.schemas.common import ProblemDetail

TAGS_METADATA: list[dict[str, Any]] = [
    {"name": "meta", "description": "Health, readiness and capability discovery."},
    {"name": "auth", "description": "Registration, login and profile management."},
    {"name": "accounts", "description": "Wallets, bank accounts, cards - and their balances."},
    {
        "name": "categories",
        "description": "Income/expense categories used to classify transactions.",
    },
    {"name": "transactions", "description": "The ledger: create, filter, aggregate."},
    {"name": "budgets", "description": "Envelope budgets with live utilisation and projections."},
    {"name": "goals", "description": "Savings goals and contributions."},
    {"name": "recurring", "description": "Salary, rent and subscription schedules."},
    {"name": "reports", "description": "Cashflow, category breakdowns, net worth and trends."},
    {"name": "insights", "description": "Rule-based financial insights and health score."},
    {"name": "data", "description": "CSV import and export."},
]

_API_DESCRIPTION = """
A production-shaped REST API for personal finance: accounts, transactions,
budgets, goals, recurring rules, analytics and rule-based insights.

**Design notes**

* Money is returned as a decimal **string** (`"1250.00"`) to avoid float rounding.
* Every error is an RFC 7807 `application/problem+json` document with a stable `code`.
* Lists are paginated (`page`, `size`) and return `total` / `pages` for the UI.
* JWTs are stateless; refresh is out of scope, tokens are short-lived (2 h default).

**Try it:** register at `POST /api/v1/auth/register`, then click **Authorize** and
paste the returned `access_token`. Or use the demo account seeded by the dev
server (`demo@pfm.app` / `demo1234`) to explore with sample data.
""".strip()

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ProblemDetail, "description": "Malformed request"},
    401: {"model": ProblemDetail, "description": "Missing or invalid bearer token"},
    403: {"model": ProblemDetail, "description": "Authenticated but not allowed"},
    404: {"model": ProblemDetail, "description": "Resource does not exist (or is not yours)"},
    409: {"model": ProblemDetail, "description": "Conflicting state (duplicate name, envelope…)"},
    422: {"model": ProblemDetail, "description": "Validation or business-rule failure"},
    429: {"model": ProblemDetail, "description": "Rate limit exceeded"},
}


def not_found(description: str = "Resource not found") -> dict[int | str, dict[str, Any]]:
    return {404: {"model": ProblemDetail, "description": description}}
