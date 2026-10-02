<div align="center">

# Personal Finance Manager API

**A production-shaped FastAPI backend for personal finance** — accounts, transactions, envelope budgets, savings goals, recurring rules, analytics and a rule-based insight engine, with a dependency-free dashboard that ships with it.

[![CI](https://github.com/sidalachandrahasreddy143-boop/Personal-Finance-Manager/actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776ab)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)
![Coverage](https://img.shields.io/badge/coverage-92%25-brightgreen)
![mypy](https://img.shields.io/badge/mypy-strict-blue)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

[Quickstart](#quickstart-60-seconds) · [API](#api-surface) · [Architecture](#architecture) · [Design decisions](#design-decisions-worth-reading) · [Testing](#testing) · [Docs](#documentation)

</div>

---

## What this is

Money apps are deceptively hard: they are full of decimal arithmetic, calendar windows, idempotent background jobs and multi-tenant data that must never leak between users. This project is a complete, tested backend that handles all of it — built as a portfolio project, engineered the way a small production service is engineered.

**It is not a tutorial CRUD app.** It has:

| | |
|---|---|
| **62 documented API operations** | every one with a summary, response model and typed errors |
| **124 tests, 92% coverage** | unit, integration and contract tests (`pytest` + `TestClient`) |
| **Strict typing** | `mypy --strict` clean across 66 modules, `ruff` clean |
| **Real migrations** | Alembic revision generated from the models, verified in CI |
| **Docker + Compose** | SQLite by default, PostgreSQL profile with a migration job |
| **CI on every push** | lint → types → tests (3.11/3.12/3.13) → migrations → container smoke test |
| **Zero-config demo** | bundled dashboard + deterministic sample data, `docker compose up` and go |

---

## Quickstart (60 seconds)

### Docker (no local Python needed)

```bash
git clone https://github.com/sidalachandrahasreddy143-boop/Personal-Finance-Manager.git
cd Personal-Finance-Manager
PFM_SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))") \
  docker compose up --build
```

Open **http://localhost:8000/app** and log in with the seeded demo account:

```
email:    demo@pfm.app
password: demo1234
```

* Dashboard → `/app` · Swagger UI → `/docs` · ReDoc → `/redoc` · OpenAPI → `/openapi.json`

### Local development

```bash
make setup     # venv + dependencies + demo data
make run       # http://localhost:8000/app  (autoreload, demo data seeded)
make check     # ruff + mypy + pytest with coverage, exactly what CI runs
```

<details>
<summary>Manual setup, without make</summary>

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

export PFM_SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
python -m app.scripts.seed_demo          # optional: 6 months of sample data
uvicorn app.main:app --reload            # http://localhost:8000/docs
```
</details>

### PostgreSQL instead of SQLite

```bash
docker compose --profile postgres up --build     # api + db + `alembic upgrade head`
# or, against your own server:
export PFM_DATABASE_URL='postgresql+psycopg://user:pass@localhost:5432/pfm'
alembic upgrade head && uvicorn app.main:app
```

---

## Dashboard

The API ships with a single-page dashboard (`app/static/`) written in **vanilla JS, hand-rolled SVG and no build step** — it exists so the backend can be *seen*, and so there is no Node toolchain to keep alive in a repo that is about Python.

* KPI header: income, expenses, net, savings rate, net worth, health score
* Income-vs-expense bar chart (6 months) and a category donut with period-over-period deltas
* Budget envelopes with live utilisation, "safe daily spend" and projected period-end spend
* Insights feed that explains every rule it fired
* Transactions table with server-side search, filtering, sorting and pagination
* CSV import (with dry-run) and export; one-click "load 6 months of sample data"

> **Screenshots:** capture them on your machine in one command — `python scripts/screenshot.py` writes `docs/screenshots/*.png` using Playwright. (They are not committed from the CI sandbox, where no browser is available — honesty over decoration.)

---

## A real session

Everything below is genuine output from this repository (demo data, seeded deterministically).

```console
$ curl -s localhost:8000/api/v1/health
{"status":"ok","version":"1.0.0","environment":"development","database":"ok","uptime_seconds":115.4,
 "checked_at":"2026-10-02T17:22:59.675232Z"}

$ TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"email":"demo@pfm.app","password":"demo1234"}' | jq -r .access_token)

$ curl -s "localhost:8000/api/v1/insights?days=30" -H "Authorization: Bearer $TOKEN" | jq .summary
{
  "total_income": "85000.00",
  "total_expense": "137570.10",
  "net": "-52570.10",
  "savings_rate": -61.85,
  "top_category": "Shopping",
  "top_category_amount": "55766.60",
  "budget_alerts": 0,
  "health_score": 40
}

$ curl -s localhost:8000/api/v1/accounts/424242 -H "Authorization: Bearer $TOKEN" -i | head -12
HTTP/1.1 404 Not Found
content-type: application/problem+json
x-request-id: ef30a0a0678d464e

{"type":"https://github.com/.../docs/ERRORS.md#not-found","title":"Resource not found",
 "status":404,"detail":"Account 424242 does not exist","code":"not-found",
 "request_id":"ef30a0a0678d464e","instance":"/api/v1/accounts/424242"}
```

Note the last one: **every** error — validation, 404, 409, 401, 429, even unhandled crashes — is an RFC 7807 `application/problem+json` document with a stable `code` and the request id that ties it to the log line.

---

## API surface

62 operations under `/api/v1`. The interactive reference is at `/docs`; this is the map.

| Group | Highlights |
|---|---|
| **auth** | `POST /auth/register` (seeds 12 starter categories), `POST /auth/login`, `POST /auth/token` (OAuth2 form for Swagger's *Authorize*), `GET/PATCH /auth/me`, `POST /auth/change-password` |
| **accounts** | CRUD + `GET /accounts/balances` (opening balance ± all activity, one grouped query), archive instead of delete when history exists |
| **categories** | CRUD, `POST /categories/seed-defaults`, income/expense kinds enforced against transaction type |
| **transactions** | CRUD + rich filtering (`search`, type, category, date range, amount range, tags, sort), pagination, `GET /transactions/suggest-category` (keyword rules) |
| **budgets** | Envelope CRUD and `GET /budgets` returning live utilisation: spent, remaining, %, days left, safe daily spend, projected period-end spend, optional rollover |
| **goals** | Goal CRUD + `POST /goals/{id}/contributions`; auto-flips to `achieved` at 100% |
| **recurring** | Rules CRUD + `POST /recurring/run` — idempotent materialisation of everything due |
| **reports** | `/reports/cashflow`, `/categories` (with previous-window deltas), `/merchants`, `/net-worth`, `/trends` (gap-filled months), `/top-transactions` |
| **insights** | `/insights` (rule engine + health score) and `/dashboard` (one round trip for the whole UI) |
| **data** | `POST /data/import/csv` (aliases, dry-run, per-row errors), `GET /data/export/transactions.csv`, `POST /data/sample` |
| **meta** | `/health` (503 when the DB is down), `/health/live`, `/meta` (capability discovery) |

### Example: create a transaction

```bash
curl -X POST localhost:8000/api/v1/transactions \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
        "account_id": 1,
        "category_id": 5,
        "amount": "1250.50",
        "type": "expense",
        "description": "Weekly groceries",
        "merchant": "BigBasket",
        "occurred_on": "2026-10-01",
        "tags": ["groceries", "weekly"]
      }'
```

```json
{
  "id": 167, "account_id": 1, "category_id": 5,
  "type": "expense", "amount": "1250.50", "currency": "INR",
  "description": "Weekly groceries", "merchant": "BigBasket",
  "occurred_on": "2026-10-01", "tags": ["groceries", "weekly"],
  "is_recurring": false, "created_at": "2026-10-02T17:19:41.238Z"
}
```

Money is a **string**, not a float. `0.1 + 0.2 != 0.3` is not an acceptable failure mode in a ledger.

---

## Architecture

```
                       ┌──────────────────────────────────────────────┐
  browser  ──────────► │  app/static/  dashboard (vanilla JS + SVG)    │
                       └───────────────────┬──────────────────────────┘
                                           │  fetch  /api/v1/*
┌──────────────────────────────────────────▼───────────────────────────────────┐
│  API layer            app/api/v1/routes/*.py                                  │
│  • HTTP concerns only: validation, status codes, pagination, OpenAPI metadata│
├──────────────────────────────────────────────────────────────────────────────┤
│  Service layer        app/services/*.py                                       │
│  • business rules: period maths, budget projections, insight rules, importer  │
│  • raises DomainError subclasses (NotFound/Conflict/BusinessRule/…)           │
├──────────────────────────────────────────────────────────────────────────────┤
│  Repository layer     app/repositories/*.py                                   │
│  • all SQLAlchemy lives here: filters, aggregates, grouped queries            │
├──────────────────────────────────────────────────────────────────────────────┤
│  Models & schema      app/models/*.py (ORM) · app/schemas/*.py (Pydantic v2)  │
├──────────────────────────────────────────────────────────────────────────────┤
│  Cross-cutting        app/core/*  settings · JWT+bcrypt · RFC7807 errors ·    │
│                        structured JSON logging · rate limiting · pagination  │
└──────────────────────────────────────────────────────────────────────────────┘
                     SQLite (dev/demo)  │  PostgreSQL (production, Alembic)
```

Dependencies point **inwards and down**: routes → services → repositories → models. Nothing in the domain layer imports FastAPI, and no SQL is written outside `app/repositories/`.

<details>
<summary><strong>Project layout</strong></summary>

```
app/
├── api/v1/routes/      auth, ledger (accounts+categories+transactions), budgets,
│                       goals, recurring, reports, insights, data, meta
├── core/               config (12-factor settings), security (JWT/bcrypt),
│                       errors (RFC 7807), logging (JSON + request ids),
│                       rate_limit, pagination, deps
├── db/                 declarative base, naming conventions, engine/session
├── models/             User, Account, Category, Transaction, Budget, Goal, RecurringRule
├── repositories/       one per aggregate + typed analytics rows
├── schemas/            request/response contracts (Pydantic v2)
├── services/           ledger, budgets, goals, recurring, reports, insights,
│                       importer, categorizer, sample_data, periods (pure maths)
├── scripts/            seed_demo, run_recurring (cron entry point)
└── static/             dashboard (index.html, styles.css, app.js, favicon.svg)
alembic/                env.py + initial migration (autogenerated from models)
tests/                  124 tests across 12 modules
docs/                   ARCHITECTURE.md, ERRORS.md, screenshots/
```

</details>

---

## Design decisions worth reading

These are the choices an interviewer will ask about — and the reasons.

**Money is `Numeric(14,2)` and serialised as a decimal string.** Floats are banned from the money path end to end. The API returns `"1250.50"`, not `1250.5`, so no client silently rounds a ledger.

**Amounts are always positive; direction is a `type` enum.** `income` / `expense` / `transfer` keeps arithmetic honest and makes `SUM(CASE WHEN type = 'income' …)` trivial. A `CheckConstraint` enforces `amount > 0` at the database level too.

**Budgets are period *instances*, not open-ended limits.** Each envelope carries `period_start`, so month-over-month comparison, rollover and "safe daily spend" are all deterministic — no `now()` hidden inside a query.

**Recurring transactions are materialised by an explicit trigger, never by a background thread in the API process.** `POST /recurring/run` and `python -m app.scripts.run_recurring` are both idempotent: a rule whose `next_run_on` is in the future is skipped, so running twice a day cannot double-charge anyone. The web tier stays stateless and horizontally scalable.

**Deletes are guarded by domain rules.** Deleting an account with history returns `422` with a `transaction_count` and suggests archiving; deleting a used category is refused. Referential integrity is `ON DELETE CASCADE/SET NULL` in the schema, but the API prefers reversible actions.

**Errors are one envelope everywhere.** `DomainError` subclasses map to RFC 7807 documents with a stable `code`, and a middleware converts even the ones raised *outside* Starlette's exception middleware (rate limiting) into the same shape.

**Insights are rule-based and explainable, not an LLM wrapper.** Every insight is a threshold on a number the API can show you (`savings-rate-strong`, `spending-spike`, `budget-over-*`, `category-concentration`, `large-transaction`, `recurring-load`). Deterministic means unit-testable, and it means the app never hallucinates a rupee figure. The thresholds live in one constants block at the top of `app/services/insights.py`.

**Multi-tenancy is enforced in the data layer, not the handler.** Every repository method takes `user_id` as its first argument; a foreign id returns `404` (not `403`), so the API doesn't leak which ids exist. Tests cover the cross-tenant cases explicitly.

**`savings_rate` compares equal-length windows.** "Previous period" is the *same number of days* immediately before the window, not "last calendar month" — otherwise a 3-day window would be compared against 31 days of spending and always look good.

---

## Testing

```bash
make test        # pytest + coverage gate (85% minimum, currently 92%)
make test-fast   # no coverage, ~5 s
```

* **Isolation:** every test runs against a throw-away SQLite database with the schema created once and tables truncated between tests; environment variables are pinned in `tests/conftest.py` before the app is imported.
* **Coverage includes the hard parts:** calendar maths (`add_months` clamping, leap years), budget projections, rollover, recurring catch-up caps, CSV alias parsing, decimal/float regressions, cross-tenant access, rate limiting, and the exact problem+json envelope.
* **Contract tests** assert every operation has a summary and that errors always carry `code` + `request_id`.

```
124 passed in 4.71s        app coverage 92%
```

CI additionally runs the suite on **Python 3.11, 3.12 and 3.13**, verifies `alembic upgrade head → check → downgrade → upgrade` leaves no drift, builds the Docker image, boots it, and hits `/health`, `/auth/login` and the dashboard inside the container.

---

## Security notes

* **Passwords:** bcrypt with a configurable cost factor (`PFM_BCRYPT_ROUNDS`), 72-byte guard, constant-time verification, identical error path for "unknown email" and "wrong password".
* **Tokens:** short-lived HS256 JWTs with `iat`, `exp`, `jti`, issuer validation and a required-claims set; the `Authorization: Bearer` flow is wired into Swagger's *Authorize* button.
* **Rate limiting:** a global fixed-window limiter plus a stricter bucket on `/auth/*` (login attempts), returning `429` + `Retry-After`-style advice. Swap the in-process store for Redis when running multiple replicas.
* **Config:** 12-factor settings with a validator that **refuses to boot** on a placeholder `PFM_SECRET_KEY`.
* **Input:** Pydantic v2 validation on every request body and query parameter, plus DB-level `CHECK` constraints and unique indexes as a second line of defence.
* **Secrets:** none in the repo; `.env` is git-ignored and `.env.example` documents every knob.

---

## Documentation

| Document | Contents |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | layering, request lifecycle, data model with the reasoning behind each column/index |
| [`docs/ERRORS.md`](docs/ERRORS.md) | the error-code catalogue returned by the API (`type`, `code`, status, when it happens) |
| `/docs`, `/redoc` | generated interactive API reference |

---

## Roadmap

Deliberately out of scope for v1 — and each one is a clean extension point:

- [ ] Refresh-token rotation + logout-all-devices
- [ ] Redis-backed rate limiting and caching for `/reports/*`
- [ ] Multi-currency with FX snapshots (the schema already stores a currency per account and transaction)
- [ ] Attachments/receipts on transactions (object storage)
- [ ] Bank feed sync (Plaid/Account Aggregator) behind the existing importer interface
- [ ] Replace the keyword categoriser with a trainable classifier (the rules are already data-driven in `app/services/categorizer.py`)

---

## License

MIT — see [LICENSE](LICENSE).

<div align="center">

Built by **Chandra Has Reddy Sida** · [GitHub](https://github.com/sidalachandrahasreddy143-boop)

</div>
