"""CSV importer tests: column aliases, formats, malformed input, dry-run."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.services.periods import today_utc
from tests.conftest import create_account


def _import(db: Session, user_id: int, content: str, **kwargs: object):
    from app.services.importer import CsvImporter

    return CsvImporter(db).import_csv(user_id, content, **kwargs)


def test_accepts_bank_style_headers_and_aliases(db: Session, seeded: dict) -> None:
    """'Narration'/'Withdrawal'/'Deposit'/'Value Date' is what real statements use."""
    content = (
        "Value Date,Narration,Withdrawal,Deposit\n"
        f"{today_utc().strftime('%d/%m/%Y')},UPI-BigBasket,2450.00,\n"
        f"{today_utc().strftime('%d/%m/%Y')},SALARY CREDIT ACME,,\"85,000.00\"\n"
    )
    summary = _import(db, seeded["user_id"], content)
    db.commit()

    assert summary.imported == 2
    assert summary.skipped == 0
    # 'Groceries' already exists from the registration seed set, so it is reused.
    assert summary.created_categories == []

    rows = db.query(__import__("app.models", fromlist=["Transaction"]).Transaction).all()
    amounts = sorted(str(row.amount) for row in rows)
    assert amounts == ["2450.00", "85000.00"]


def test_semicolon_delimiter_is_sniffed(db: Session, seeded: dict) -> None:
    content = "date;description;amount\n" f"{today_utc().isoformat()};Semicolon file;-100.50\n"
    summary = _import(db, seeded["user_id"], content)
    assert summary.imported == 1


def test_negative_and_parenthesised_amounts_become_expenses(db: Session, seeded: dict) -> None:
    content = (
        "date,description,amount\n"
        f"{today_utc().isoformat()},Plain negative,-500\n"
        f"{today_utc().isoformat()},Accounting negative,(750.25)\n"
        f"{today_utc().isoformat()},Positive is income,1000\n"
    )
    summary = _import(db, seeded["user_id"], content)
    assert summary.imported == 3

    from app.models import Transaction
    from app.models.enums import TransactionType

    kinds = {row.description: row.type for row in db.query(Transaction).all()}
    assert kinds["Plain negative"] is TransactionType.EXPENSE
    assert kinds["Accounting negative"] is TransactionType.EXPENSE
    assert kinds["Positive is income"] is TransactionType.INCOME


def test_explicit_type_column_wins_over_the_sign(db: Session, seeded: dict) -> None:
    """Banks sometimes export all-positive amounts with the direction in a column."""
    content = (
        "date,description,amount,type\n"
        f"{today_utc().isoformat()},Card payment,1500,expense\n"
        f"{today_utc().isoformat()},Refund,-900,income\n"
    )
    _import(db, seeded["user_id"], content)
    db.commit()

    from app.models import Transaction
    from app.models.enums import TransactionType

    kinds = {row.description: row.type for row in db.query(Transaction).all()}
    assert kinds["Card payment"] is TransactionType.EXPENSE
    assert kinds["Refund"] is TransactionType.INCOME
    assert all(row.amount > 0 for row in db.query(Transaction).all())


def test_bad_rows_are_reported_not_fatal(db: Session, seeded: dict) -> None:
    content = (
        "date,description,amount\n"
        f"{today_utc().isoformat()},Fine,-100\n"
        "not-a-date,broken,-200\n"
        f"{today_utc().isoformat()},zero,0\n"
    )
    summary = _import(db, seeded["user_id"], content)

    assert summary.imported == 1
    assert summary.skipped == 2
    assert [error.row for error in summary.errors] == [3, 4]
    assert "Unrecognised date" in summary.errors[0].error


def test_dry_run_writes_nothing(db: Session, seeded: dict) -> None:
    content = "date,description,amount\n" f"{today_utc().isoformat()},Preview row,-100\n"
    summary = _import(db, seeded["user_id"], content, dry_run=True)

    assert summary.dry_run is True
    assert summary.imported == 1

    from app.models import Account, Transaction

    assert db.query(Transaction).count() == 0
    assert db.query(Account).count() == 1  # the 'Imported Account' was rolled back too


def test_existing_account_is_reused_by_name(db: Session, seeded: dict) -> None:
    account = create_account(db, seeded["user_id"], name="Statement Account")
    db.commit()

    content = (
        "date,description,amount,account\n"
        f"{today_utc().isoformat()},Row,-100,Statement Account\n"
    )
    summary = _import(db, seeded["user_id"], content)
    db.commit()

    assert summary.created_accounts == []
    from app.models import Transaction

    assert db.query(Transaction).one().account_id == account.id


def test_create_missing_false_falls_back_to_default_account(db: Session, seeded: dict) -> None:
    content = (
        "date,description,amount,account,category\n"
        f"{today_utc().isoformat()},Row,-100,Unknown Bank,Unknown Category\n"
    )
    summary = _import(
        db,
        seeded["user_id"],
        content,
        create_missing=False,
        default_account_id=seeded["account_id"],
    )
    db.commit()

    assert summary.created_accounts == []
    assert summary.created_categories == []
    from app.models import Transaction

    row = db.query(Transaction).one()
    assert row.account_id == seeded["account_id"]
    assert row.category_id is None  # uncategorised, never guessed silently


def test_missing_required_columns_raises(db: Session, seeded: dict) -> None:
    with pytest.raises(ValueError, match="'date' and 'description'"):
        _import(db, seeded["user_id"], "amount,merchant\n100,Amazon\n")

    with pytest.raises(ValueError, match="amount"):
        _import(db, seeded["user_id"], "date,description\n2026-01-01,No amount\n")

    with pytest.raises(ValueError, match="header row"):
        _import(db, seeded["user_id"], "")


def test_tags_and_notes_are_preserved(db: Session, seeded: dict) -> None:
    content = (
        "date,description,amount,tags,notes\n"
        f'{today_utc().isoformat()},Tagged row,-100,"travel, work",Receipt in email\n'
    )
    _import(db, seeded["user_id"], content)
    db.commit()

    from app.models import Transaction

    row = db.query(Transaction).one()
    assert row.tag_list == ["travel", "work"]
    assert row.notes == "Receipt in email"


def test_dates_in_several_formats(db: Session, seeded: dict) -> None:
    content = (
        "date,description,amount\n"
        "2026-01-15,ISO,10\n"
        "15/01/2026,Day first,20\n"
        "15-01-2026,Dashed,30\n"
        "15 Jan 2026,Month name,40\n"
    )
    summary = _import(db, seeded["user_id"], content)
    assert summary.imported == 4

    from app.models import Transaction

    assert {row.occurred_on for row in db.query(Transaction).all()} == {dt.date(2026, 1, 15)}
