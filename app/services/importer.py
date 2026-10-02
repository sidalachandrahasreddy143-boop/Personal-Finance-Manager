"""CSV import with per-row validation and dry-run support.

Accepts the export format of most banks/budgeting apps plus a generous set of
column aliases. Rows that fail validation are reported instead of aborting the
whole import, because a 2,000-row statement from a bank *will* contain junk.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal, InvalidOperation
from typing import TypedDict

from sqlalchemy.orm import Session

from app.models import Account, Category
from app.models.enums import CategoryKind, TransactionType
from app.repositories.accounts import AccountRepository
from app.repositories.categories import CategoryRepository
from app.repositories.transactions import TransactionRepository
from app.schemas.importer import ImportRowError, ImportSummary
from app.schemas.ledger import AccountCreate, CategoryCreate
from app.services.categorizer import categorizer
from app.services.ledger import LedgerService

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y", "%d %b %Y", "%d %B %Y")


class ParsedRow(TypedDict):
    """A validated row, ready to become a Transaction."""

    occurred_on: dt.date
    description: str
    amount: Decimal
    type: TransactionType
    category: str | None
    account: str | None
    merchant: str | None
    notes: str | None
    tags: str | None


_ALIASES: dict[str, set[str]] = {
    "date": {"date", "transaction date", "txn date", "value date", "occurred_on"},
    "description": {"description", "narration", "details", "particulars", "memo", "note"},
    "amount": {"amount", "value", "transaction amount", "debit/credit amount"},
    "debit": {"debit", "withdrawal", "withdrawal amt", "dr"},
    "credit": {"credit", "deposit", "deposit amt", "cr"},
    "type": {"type", "transaction type", "txn type", "kind"},
    "category": {"category", "categories"},
    "account": {"account", "account name", "bank", "card"},
    "merchant": {"merchant", "payee", "vendor", "beneficiary"},
    "tags": {"tags", "labels"},
    "notes": {"notes", "remarks", "comment"},
}


def _normalise_header(header: str) -> str:
    cleaned = header.strip().lower().replace("_", " ")
    for field, aliases in _ALIASES.items():
        if cleaned in aliases:
            return field
    return cleaned


def _parse_date(raw: str) -> dt.date:
    value = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date '{raw}' (try YYYY-MM-DD)")


def _parse_amount(raw: str) -> Decimal:
    cleaned = raw.strip().replace(",", "").replace("₹", "").replace("$", "").replace(" ", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):  # accounting negatives
        cleaned = f"-{cleaned[1:-1]}"
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"Unrecognised amount '{raw}'") from exc


class CsvImporter:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.ledger = LedgerService(db)
        self.accounts = AccountRepository(db)
        self.categories = CategoryRepository(db)
        self.transactions = TransactionRepository(db)

    def import_csv(
        self,
        user_id: int,
        content: bytes | str,
        *,
        default_account_id: int | None = None,
        create_missing: bool = True,
        dry_run: bool = False,
        delimiter: str | None = None,
    ) -> ImportSummary:
        text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
        sample = text[:4096]
        if delimiter is None:
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","

        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError("The uploaded file has no header row")

        mapping = {_normalise_header(h): h for h in reader.fieldnames if h}
        if "date" not in mapping or "description" not in mapping:
            raise ValueError(
                "CSV must contain at least 'date' and 'description' columns; "
                f"found {', '.join(reader.fieldnames)}"
            )
        if not {"amount", "debit", "credit"} & set(mapping):
            raise ValueError(
                "CSV must contain an 'amount' column (or separate debit/credit columns)"
            )

        default_account = None
        if default_account_id is not None:
            default_account = self.accounts.get_for_user(user_id, default_account_id)
        else:
            existing = self.accounts.list_for_user(user_id)
            default_account = existing[0] if existing else None

        created_accounts: set[str] = set()
        created_categories: set[str] = set()
        errors: list[ImportRowError] = []
        imported = 0
        skipped = 0
        total_rows = 0

        for index, raw_row in enumerate(reader, start=2):  # row 1 is the header
            total_rows += 1
            try:
                parsed = self._parse_row(raw_row, mapping)
            except ValueError as exc:
                errors.append(ImportRowError(row=index, error=str(exc)))
                skipped += 1
                continue

            try:
                account_name = parsed.get("account") or (
                    default_account.name if default_account else None
                )
                if account_name is None:
                    account_name = "Imported Account"
                account = self._resolve_account(
                    user_id, account_name, create_missing, created_accounts, default_account
                )

                category = self._resolve_category(
                    user_id, parsed, create_missing, created_categories
                )

                if not dry_run:
                    self.transactions.create(
                        user_id=user_id,
                        account_id=account.id,
                        category_id=category.id if category else None,
                        type=parsed["type"],
                        amount=parsed["amount"],
                        currency=account.currency,
                        description=parsed["description"],
                        merchant=parsed.get("merchant"),
                        occurred_on=parsed["occurred_on"],
                        notes=parsed.get("notes"),
                        tags=parsed.get("tags"),
                        is_recurring=False,
                    )
                imported += 1
            except Exception as exc:
                errors.append(ImportRowError(row=index, error=str(exc)))
                skipped += 1

        if dry_run:
            self.db.rollback()

        return ImportSummary(
            imported=imported,
            skipped=skipped,
            total_rows=total_rows,
            created_accounts=sorted(created_accounts),
            created_categories=sorted(created_categories),
            errors=errors[:50],
            dry_run=dry_run,
        )

    # ------------------------------------------------------------------ #
    def _parse_row(self, row: dict[str, str | None], mapping: dict[str, str]) -> ParsedRow:
        def get(field: str) -> str:
            column = mapping.get(field)
            return (row.get(column) or "").strip() if column else ""

        occurred_on = _parse_date(get("date"))
        description = get("description") or get("merchant") or "Imported transaction"

        amount_raw = get("amount")
        debit = get("debit")
        credit = get("credit")

        txn_type = get("type").lower()
        if amount_raw:
            amount = _parse_amount(amount_raw)
            if amount == 0:
                raise ValueError("Amount cannot be zero")
            resolved_type = TransactionType.EXPENSE if amount < 0 else TransactionType.INCOME
            if txn_type in {"expense", "debit", "dr", "withdrawal"}:
                resolved_type = TransactionType.EXPENSE
            elif txn_type in {"income", "credit", "cr", "deposit"}:
                resolved_type = TransactionType.INCOME
            amount = abs(amount)
        elif debit or credit:
            if debit:
                amount, resolved_type = _parse_amount(debit), TransactionType.EXPENSE
            else:
                amount, resolved_type = _parse_amount(credit), TransactionType.INCOME
            amount = abs(amount)
            if amount == 0:
                raise ValueError("Amount cannot be zero")
        else:
            raise ValueError("Row has no amount value")

        tags = [t.strip().lower() for t in get("tags").replace(";", ",").split(",") if t.strip()]
        merchant = get("merchant")
        return ParsedRow(
            occurred_on=occurred_on,
            description=description[:255],
            amount=amount,
            type=resolved_type,
            category=get("category") or None,
            account=get("account") or None,
            merchant=merchant[:120] if merchant else None,
            notes=get("notes") or None,
            tags=",".join(tags) if tags else None,
        )

    def _resolve_account(
        self,
        user_id: int,
        name: str,
        create_missing: bool,
        created: set[str],
        fallback: Account | None,
    ) -> Account:
        existing = next(
            (
                a
                for a in self.accounts.list_for_user(user_id, include_archived=True)
                if a.name.lower() == name.lower()
            ),
            None,
        )
        if existing:
            return existing
        if not create_missing:
            if fallback is None:
                raise ValueError(f"Account '{name}' does not exist")
            return fallback
        account = self.ledger.create_account(user_id, AccountCreate(name=name[:120]))
        created.add(account.name)
        return account

    def _resolve_category(
        self,
        user_id: int,
        parsed: ParsedRow,
        create_missing: bool,
        created: set[str],
    ) -> Category | None:
        name = parsed.get("category")
        if not name:
            name = categorizer.suggest(parsed.get("description"), parsed.get("merchant"))
        if not name:
            return None

        kind = (
            CategoryKind.INCOME
            if parsed["type"] is TransactionType.INCOME
            else CategoryKind.EXPENSE
        )
        existing = self.categories.find_by_name(user_id, str(name), kind)
        if existing:
            return existing
        if not create_missing:
            return None
        category = self.ledger.create_category(
            user_id, CategoryCreate(name=str(name)[:80], kind=kind)
        )
        created.add(category.name)
        return category
