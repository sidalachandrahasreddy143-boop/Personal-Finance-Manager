"""CSV import and export endpoints."""

from __future__ import annotations

import csv
import datetime as dt
import io

from fastapi import APIRouter, File, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.openapi import ERROR_RESPONSES
from app.core.deps import CurrentUser, DbSession
from app.core.errors import BusinessRuleError
from app.repositories.transactions import TransactionQuery
from app.schemas.importer import ImportSummary
from app.services.importer import CsvImporter
from app.services.ledger import LedgerService
from app.services.sample_data import generate_sample_data

router = APIRouter(prefix="/data", tags=["data"])

CSV_TEMPLATE = (
    "date,description,amount,type,category,account,merchant,tags,notes\n"
    "2026-09-01,September salary,85000,income,Salary,HDFC Savings,Acme Corp,salary,\n"
    "2026-09-03,BigBasket order,2450,expense,Groceries,HDFC Savings,BigBasket,groceries,\n"
    "2026-09-05,Uber to airport,780,expense,Transport,Cash,Uber,travel,\n"
    "2026-09-10,Netflix subscription,649,expense,Entertainment,HDFC Savings,Netflix,subscription,\n"
)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


@router.post(
    "/import/csv",
    response_model=ImportSummary,
    summary="Import transactions from a bank/card CSV",
    description=(
        "Accepts a generous set of column aliases (`narration`, `withdrawal`, `deposit`, "
        "`value date`, ...), both ISO and D/M/Y dates, and thousands separators. "
        "Rows are validated individually - bad rows are reported, good ones still import. "
        "Use `dry_run=true` to preview without writing anything."
    ),
    responses=ERROR_RESPONSES,
)
async def import_csv(
    user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(..., description="CSV file (max 5 MB)"),
    default_account_id: int | None = Query(None, description="Account to attach rows without one"),
    create_missing: bool = Query(True, description="Auto-create unknown accounts/categories"),
    dry_run: bool = Query(False, description="Validate and report, write nothing"),
) -> ImportSummary:
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise BusinessRuleError("File too large - split it into chunks under 5 MB")
    if not content.strip():
        raise BusinessRuleError("Uploaded file is empty")

    try:
        return CsvImporter(db).import_csv(
            user.id,
            content,
            default_account_id=default_account_id,
            create_missing=create_missing,
            dry_run=dry_run,
        )
    except ValueError as exc:
        raise BusinessRuleError(str(exc)) from exc


@router.post(
    "/sample",
    summary="Load six months of sample data",
    description=(
        "Generates a realistic history (salary, rent, groceries, subscriptions, budgets, "
        "goals and recurring rules) for the **current** user. Deterministic, and refuses to "
        "run when the account already has transactions."
    ),
    responses=ERROR_RESPONSES,
)
def load_sample_data(user: CurrentUser, db: DbSession) -> dict[str, object]:
    summary = generate_sample_data(db, user.id, months=6)
    return {
        "accounts": summary.accounts,
        "categories": summary.categories,
        "transactions": summary.transactions,
        "budgets": summary.budgets,
        "goals": summary.goals,
        "rules": summary.rules,
    }


@router.get(
    "/import/template",
    summary="Download a CSV template",
    response_class=StreamingResponse,
)
def csv_template() -> StreamingResponse:
    return StreamingResponse(
        iter([CSV_TEMPLATE]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="pfm-import-template.csv"'},
    )


@router.get(
    "/export/transactions.csv",
    summary="Export the ledger as CSV",
    description="Round-trips with the importer: export, edit in a spreadsheet, re-import.",
    response_class=StreamingResponse,
)
def export_transactions(
    user: CurrentUser,
    db: DbSession,
    date_from: dt.date | None = Query(None, alias="from"),
    date_to: dt.date | None = Query(None, alias="to"),
) -> StreamingResponse:
    service = LedgerService(db)
    items, _total = service.list_transactions(
        user.id,
        TransactionQuery(date_from=date_from, date_to=date_to, sort="occurred_on", order="asc"),
        offset=0,
        limit=100_000,
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "date",
            "description",
            "amount",
            "type",
            "category",
            "account",
            "merchant",
            "tags",
            "notes",
        ]
    )
    for txn in items:
        writer.writerow(
            [
                txn.occurred_on.isoformat(),
                txn.description,
                f"{txn.amount:.2f}",
                txn.type.value,
                txn.category.name if txn.category else "",
                txn.account.name,
                txn.merchant or "",
                ",".join(txn.tag_list),
                (txn.notes or "").replace("\n", " "),
            ]
        )
    buffer.seek(0)
    filename = f"transactions-{dt.date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        status_code=status.HTTP_200_OK,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
