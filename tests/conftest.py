"""Pytest fixtures: an isolated in-memory database and an authenticated client.

Environment variables are set *before* the application is imported so the whole
suite runs against SQLite in memory - no fixtures on disk, no network.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from collections.abc import Generator

# A throw-away SQLite *file* (not `:memory:`) gives every session its own
# connection, so API requests and test fixtures see each other's committed data.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="pfm-tests-")

os.environ.setdefault("PFM_ENVIRONMENT", "test")
os.environ.setdefault("PFM_SECRET_KEY", "test-secret-key-not-for-production-0123456789")
os.environ.setdefault("PFM_DATABASE_URL", f"sqlite:///{_TEST_DB_DIR}/test.db")
os.environ.setdefault("PFM_RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("PFM_SEED_DEMO_USER", "false")
os.environ.setdefault("PFM_BCRYPT_ROUNDS", "4")  # keep hashing fast in tests

import datetime as dt  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Account, Budget, Category, Transaction, User  # noqa: E402
from app.models.enums import (  # noqa: E402
    AccountType,
    BudgetPeriod,
    CategoryKind,
    TransactionType,
)
from app.services.periods import month_start, today_utc  # noqa: E402

TEST_PASSWORD = "Str0ng-pass!"


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Generator[None, None, None]:
    """Create the schema once per test session, drop it at the end."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    shutil.rmtree(_TEST_DB_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    """Truncate all tables between tests so they cannot leak into each other."""
    yield
    with SessionLocal() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()


@pytest.fixture
def db() -> Generator[Session, None, None]:
    """A plain session for service/repository level tests."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    finally:
        session.close()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def user(client: TestClient) -> dict[str, object]:
    """Register a fresh user and return its token + profile."""
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": TEST_PASSWORD,
            "full_name": "Test User",
            "currency": "INR",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    return {"email": email, "password": TEST_PASSWORD, **payload}


@pytest.fixture
def auth(client: TestClient, user: dict[str, object]) -> dict[str, str]:
    """Authorization header for the registered ``user`` fixture."""
    return {"Authorization": f"Bearer {user['access_token']}"}


# --------------------------------------------------------------------------- #
# Data helpers (used directly by tests that need a populated ledger)
# --------------------------------------------------------------------------- #


def create_account(
    db: Session,
    user_id: int,
    *,
    name: str = "Test Bank",
    type_: AccountType = AccountType.BANK,
    opening_balance: str = "10000.00",
) -> Account:
    account = Account(
        user_id=user_id,
        name=name,
        type=type_,
        currency="INR",
        opening_balance=Decimal(opening_balance),
    )
    db.add(account)
    db.flush()
    return account


def create_category(
    db: Session,
    user_id: int,
    *,
    name: str = "Groceries",
    kind: CategoryKind = CategoryKind.EXPENSE,
) -> Category:
    category = Category(user_id=user_id, name=name, kind=kind)
    db.add(category)
    db.flush()
    return category


def create_transaction(
    db: Session,
    user_id: int,
    account: Account,
    *,
    amount: str = "500.00",
    type_: TransactionType = TransactionType.EXPENSE,
    category: Category | None = None,
    occurred_on: dt.date | None = None,
    description: str = "Test transaction",
    merchant: str | None = None,
) -> Transaction:
    txn = Transaction(
        user_id=user_id,
        account_id=account.id,
        category_id=category.id if category else None,
        type=type_,
        amount=Decimal(amount),
        currency="INR",
        description=description,
        merchant=merchant,
        occurred_on=occurred_on or today_utc(),
    )
    db.add(txn)
    db.flush()
    return txn


def create_budget(
    db: Session,
    user_id: int,
    category: Category,
    *,
    limit: str = "5000.00",
    period_start: dt.date | None = None,
) -> Budget:
    budget = Budget(
        user_id=user_id,
        category_id=category.id,
        amount_limit=Decimal(limit),
        period=BudgetPeriod.MONTHLY,
        period_start=period_start or month_start(today_utc()),
    )
    db.add(budget)
    db.flush()
    return budget


def db_user(db: Session, email: str) -> User:
    user = db.query(User).filter(User.email == email).one()
    return user


@pytest.fixture
def seeded(client: TestClient, db: Session, user: dict[str, object]) -> dict[str, object]:
    """The registered ``user``, plus one bank account and two categories."""
    user_row = db_user(db, str(user["email"]))

    account = create_account(db, user_row.id)
    # Registration already seeded the default taxonomy - reuse it.
    groceries = db.query(Category).filter_by(user_id=user_row.id, name="Groceries").one()
    salary = db.query(Category).filter_by(user_id=user_row.id, name="Salary").one()
    db.commit()

    return {
        "user_id": user_row.id,
        "email": user["email"],
        "token": user["access_token"],
        "headers": {"Authorization": f"Bearer {user['access_token']}"},
        "account": account,
        "account_id": account.id,
        "groceries": groceries,
        "groceries_id": groceries.id,
        "salary": salary,
        "salary_id": salary.id,
    }
