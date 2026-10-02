# Architecture & data model

This document explains *why* the code is shaped the way it is. The README covers
what exists; this covers the reasoning a reviewer would otherwise have to reverse
engineer.

## 1. Layering

```
routes  ──►  services  ──►  repositories  ──►  models (ORM)  ──►  database
   │             │               │
   │             │               └── the only place SQLAlchemy expressions are built
   │             └────────────────── business rules, calendar maths, domain errors
   └──────────────────────────────── HTTP: validation, status codes, OpenAPI metadata
```

Rules that keep this honest:

1. **Routes never build queries and never touch `db.add()`.** They translate HTTP
   into a service call and back.
2. **Services never import FastAPI.** They raise `DomainError` subclasses
   (`NotFoundError`, `ConflictError`, `BusinessRuleError`, …) which the API layer
   maps onto status codes in one place (`app/core/errors.py`).
3. **Repositories return ORM objects or typed `NamedTuple` rows** — never
   Pydantic models, never dicts assembled by hand.
4. **Schemas are the contract.** Response models are declared on every route, so
   `/openapi.json` is accurate enough to generate clients from.

The payoff: `tests/test_periods.py` and much of `tests/test_insights.py` run
without a database or an HTTP client, because the interesting logic is pure.

## 2. Request lifecycle

```
client
  │
  ├─ RequestContextMiddleware   assigns/propagates X-Request-ID, times the request,
  │                             emits one structured log line per request
  ├─ rate_limit_middleware      fixed-window limiter (converted to problem+json here,
  │                             because middleware runs outside Starlette's handlers)
  ├─ CORSMiddleware             configurable origins (the bundled UI is same-origin)
  ├─ GZipMiddleware             compresses responses > 1 KB
  ├─ Exception handlers         DomainError → problem+json, validation → problem+json,
  │                             HTTPException → problem+json, Exception → 500 + log
  └─ route → dependency (get_db, get_current_user) → service → repository
                                          │
                                          └─ session.commit() on success, rollback on error
```

`get_db` owns the transaction boundary: the dependency yields a session, commits
if the handler returned normally, rolls back if anything raised, and always
closes. That means a partially-applied business operation can never be committed.

## 3. Data model

```
users ──┬── accounts ──────────┐
        │                      │
        ├── categories ──┬─────┼── transactions ──── recurring_rules
        │                │     │                        │
        ├── budgets ─────┘     └────────────────────────┘
        └── goals
```

### `users`
Identity and preferences. `email` is stored lowercase and uniquely indexed;
`currency` is the display default. Passwords are only ever stored as bcrypt hashes.

### `accounts`
A place money sits. `opening_balance` is the starting point; the *current*
balance is derived (`opening_balance + Σincome − Σexpense`) rather than stored,
because a cached balance is a bug waiting to happen. `is_archived` exists so a
closed account disappears from pickers without destroying history.

### `categories`
`kind` is `income` or `expense` and is enforced against the transaction type —
this is what stops *Salary* from being used for a coffee and keeps the category
breakdown reports meaningful. `(user_id, name, kind)` is unique.

### `transactions`
The heart of the model:

| Choice | Reason |
|---|---|
| `amount` always positive | direction lives in `type`; `CHECK (amount > 0)` in the DB |
| `Numeric(14, 2)` | exact decimal arithmetic, no float drift |
| `type ∈ {income, expense, transfer}` | one ledger for everything; reports `SUM(CASE …)` |
| `category_id` nullable, `ON DELETE SET NULL` | uncategorised rows are valid; deleting a category never deletes money history |
| `recurring_rule_id` | lets the UI show "posted automatically" and makes the job auditable |
| `tags` as CSV | single-user scale, and `ILIKE` filtering would not benefit from a join table here; documented as the first thing to normalise at scale |
| composite indexes `(user_id, occurred_on)`, `(user_id, category_id)`, `(user_id, merchant)` | every read path is user-scoped and time-ordered |

### `budgets`
A budget is an **envelope instance**: `(category, period, period_start)` is unique,
so "the October groceries envelope" is a row, not a calculation. That makes
rollover (`unused = limit − spent(previous window)`) explicit, and it makes
month-over-month comparisons trivial.

### `goals`
`progress_pct` is a property, not a column — one source of truth. `status`
flips to `achieved` inside the service when a contribution crosses the target.

### `recurring_rules`
`next_run_on` is the cursor. Materialising a rule posts one transaction per due
occurrence and advances the cursor; `MAX_CATCHUP_ITERATIONS` (120) stops a
forgotten daily rule from flooding the ledger when it finally runs, and a rule
past its `end_date` deactivates itself.

## 4. Cross-cutting concerns

**Configuration** (`app/core/config.py`) is 12-factor: every knob is a `PFM_`-
prefixed environment variable with a safe default. A validator refuses to start
with a placeholder secret key.

**Errors** (`app/core/errors.py`) define the domain exception hierarchy and the
single place that turns them into RFC 7807 documents. The `type` URLs point at
[`ERRORS.md`](ERRORS.md), so an error in production links to its own documentation.

**Logging** (`app/core/logging.py`) emits one JSON object per line with a
`request_id` contextvar, so a log line, an error response and a client bug report
can be correlated. Uvicorn's handlers are rerouted through the same pipeline.

**Money serialisation** (`app/schemas/common.py`) uses a Pydantic
`PlainSerializer` so `Decimal` becomes `"1250.50"` on the wire while staying
`Decimal` in Python.

**Pagination** (`app/core/pagination.py`) is one dependency returning
`{items, total, page, size, pages}` — the metadata a UI needs to render controls
without guessing.

## 5. What I would change at scale

| Today | Next step |
|---|---|
| Sync SQLAlchemy sessions in FastAPI's threadpool | `AsyncSession` + `asyncpg`, or keep sync and scale with more workers (simpler, and fine until ~thousands of rps) |
| In-process fixed-window rate limiter | Redis token bucket shared across replicas |
| `tags` CSV column | `tags` table + join, or a `text[]` column on PostgreSQL |
| Reports computed on demand | Materialised monthly rollups refreshed by the recurring worker |
| Single-region SQLite in the demo, PostgreSQL in compose | Managed PostgreSQL with read replicas for analytics |
| Keyword categoriser | Learn from user corrections (the rules module is already data-driven) |
