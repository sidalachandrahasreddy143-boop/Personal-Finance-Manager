# Error catalogue

Every error the API returns is an [RFC 7807](https://www.rfc-editor.org/rfc/rfc7807) problem document served as
`application/problem+json`:

```json
{
  "type": "https://github.com/sidalachandrahasreddy143-boop/Personal-Finance-Manager/blob/main/docs/ERRORS.md#not-found",
  "title": "Resource not found",
  "status": 404,
  "detail": "Account 424242 does not exist",
  "code": "not-found",
  "request_id": "ef30a0a0678d464e",
  "instance": "/api/v1/accounts/424242"
}
```

* `code` is **stable** — branch on it, never on `detail`.
* `request_id` also appears in the `X-Request-ID` response header and in the structured log line for that request.
* Validation failures add an `errors` array of `{field, message, type}`.
* Business-rule failures may add context (for example `transaction_count`).

| `code` | Status | Raised when | Added context |
|---|---|---|---|
| `validation-error` | 422 | Request body or query parameter fails Pydantic validation | `errors[]` |
| `not-found` | 404 | The resource does not exist **or belongs to another user** | — |
| `unauthorized` | 401 | Missing/expired/invalid bearer token, bad credentials, deactivated account | — |
| `forbidden` | 403 | Authenticated but not permitted (reserved for future role support) | — |
| `conflict` | 409 | Duplicate account or category name, duplicate budget envelope | — |
| `business-rule` | 422 | A domain invariant would be broken (see below) | varies |
| `rate-limited` | 429 | More requests than the window allows | `limit_per_minute` |
| `http-404` | 404 | Unknown route | — |
| `internal-error` | 500 | Unhandled exception (logged with a stack trace, never leaked to the client) | — |

## Business-rule failures

These are the interesting ones — the API refuses work that would corrupt the ledger or lose history:

| Detail contains | Why |
|---|---|
| `still has N transaction(s)` | Deleting an account with history. Archive it instead, or move the transactions first. Response includes `transaction_count`. |
| `is used by N transaction(s)` | Deleting a category that transactions reference. Archive it to hide it from pickers without losing history. |
| `is a expense category; a expense transaction needs …` | Category kind and transaction type must match: an `income` transaction cannot be filed under *Groceries*. |
| `is archived` | The chosen category is archived and no longer selectable. |
| `Transfers cannot use an income category` | Transfers keep the ledger symmetric and carry no income/expense semantics. |
| `budgets only track spending` | Budgeting an income category. |
| `end_date must be on or after next_run_on` | A recurring rule that could never fire. |
| `File too large` / `Uploaded file is empty` / `must contain at least 'date' and 'description'` | CSV import guard rails (5 MB limit). |
| `This account already has transactions` | `POST /data/sample` refuses to double-seed sample data. |

## Example: validation error

```console
$ curl -s -X POST localhost:8000/api/v1/accounts \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"name": "", "type": "nope"}' | jq
{
  "type": "…/docs/ERRORS.md#validation-error",
  "title": "Request validation failed",
  "status": 422,
  "detail": "2 field(s) failed validation.",
  "code": "validation-error",
  "request_id": "8f2c…",
  "instance": "/api/v1/accounts",
  "errors": [
    {"field": "name", "message": "String should have at least 1 character", "type": "string_too_short"},
    {"field": "type", "message": "Input should be 'cash', 'bank', …", "type": "enum"}
  ]
}
```

## Example: rate limited

```console
$ curl -s localhost:8000/api/v1/auth/login -d '{…}' … | jq
{
  "type": "…/docs/ERRORS.md#rate-limited",
  "title": "Too many requests",
  "status": 429,
  "detail": "Rate limit exceeded. Please slow down and retry in a minute.",
  "code": "rate-limited",
  "limit_per_minute": 10
}
```
