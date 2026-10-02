"""Transaction data access: filtered listing plus analytical aggregates.

Aggregates return typed :class:`~typing.NamedTuple` rows rather than loose
tuples so callers get attribute access and mypy checks the shapes.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import Select, case, func, or_, select

from app.core.errors import NotFoundError
from app.models import Account, Category, Transaction
from app.models.enums import TransactionType
from app.repositories.base import BaseRepository

_SORTABLE = {
    "occurred_on": Transaction.occurred_on,
    "amount": Transaction.amount,
    "created_at": Transaction.created_at,
    "description": Transaction.description,
}


class MonthlyCashflowRow(NamedTuple):
    """One ``GROUP BY`` month bucket."""

    period: str
    income: Decimal
    expense: Decimal


class CategoryBreakdownRow(NamedTuple):
    category_id: int | None
    name: str
    icon: str
    color: str
    total: Decimal
    transaction_count: int


class MerchantRow(NamedTuple):
    merchant: str
    total: Decimal
    transaction_count: int


class TopTransactionRecord(NamedTuple):
    id: int
    description: str
    amount: Decimal
    occurred_on: dt.date
    category: str | None
    account: str
    type: TransactionType


@dataclass(slots=True)
class TransactionQuery:
    """Every filter the ledger endpoint supports."""

    search: str | None = None
    account_id: int | None = None
    category_id: int | None = None
    type: TransactionType | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    tags: list[str] | None = None
    sort: str = "occurred_on"
    order: str = "desc"


class TransactionRepository(BaseRepository[Transaction]):
    model = Transaction

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def build_query(self, user_id: int, filters: TransactionQuery) -> Select[tuple[Transaction]]:
        """Turn a filter object into a SQLAlchemy ``SELECT`` (no execution)."""
        stmt = select(Transaction).where(Transaction.user_id == user_id)

        if filters.search:
            pattern = f"%{filters.search.strip()}%"
            stmt = stmt.where(
                or_(
                    Transaction.description.ilike(pattern),
                    Transaction.merchant.ilike(pattern),
                    Transaction.notes.ilike(pattern),
                    Transaction.tags.ilike(pattern),
                )
            )
        if filters.account_id is not None:
            stmt = stmt.where(Transaction.account_id == filters.account_id)
        if filters.category_id is not None:
            stmt = stmt.where(Transaction.category_id == filters.category_id)
        if filters.type is not None:
            stmt = stmt.where(Transaction.type == filters.type)
        if filters.date_from is not None:
            stmt = stmt.where(Transaction.occurred_on >= filters.date_from)
        if filters.date_to is not None:
            stmt = stmt.where(Transaction.occurred_on <= filters.date_to)
        if filters.min_amount is not None:
            stmt = stmt.where(Transaction.amount >= filters.min_amount)
        if filters.max_amount is not None:
            stmt = stmt.where(Transaction.amount <= filters.max_amount)
        for tag in filters.tags or []:
            stmt = stmt.where(Transaction.tags.ilike(f"%{tag.strip().lower()}%"))

        column = _SORTABLE.get(filters.sort, Transaction.occurred_on)
        ordering = column.desc() if filters.order.lower() == "desc" else column.asc()
        return stmt.order_by(ordering, Transaction.id.desc())

    def list_for_user(
        self, user_id: int, filters: TransactionQuery, *, offset: int = 0, limit: int = 50
    ) -> tuple[list[Transaction], int]:
        stmt = self.build_query(user_id, filters)
        total = self.count(stmt)
        items = list(self.db.scalars(stmt.offset(offset).limit(limit)).all())
        return items, total

    def get_for_user(self, user_id: int, transaction_id: int) -> Transaction:
        txn = self.db.scalar(
            select(Transaction).where(
                Transaction.id == transaction_id, Transaction.user_id == user_id
            )
        )
        if txn is None:
            raise NotFoundError(f"Transaction {transaction_id} does not exist")
        return txn

    # ------------------------------------------------------------------ #
    # Aggregates
    # ------------------------------------------------------------------ #
    def sum_by_type(self, user_id: int, date_from: dt.date, date_to: dt.date) -> dict[str, Decimal]:
        """Total per transaction type for a window (missing types default to 0)."""
        rows = self.db.execute(
            select(Transaction.type, func.coalesce(func.sum(Transaction.amount), 0))
            .where(
                Transaction.user_id == user_id,
                Transaction.occurred_on >= date_from,
                Transaction.occurred_on <= date_to,
            )
            .group_by(Transaction.type)
            .select_from(Transaction)
        ).all()

        totals = {txn_type.value: Decimal("0.00") for txn_type in TransactionType}
        for txn_type, total in rows:
            key = txn_type.value if isinstance(txn_type, TransactionType) else str(txn_type)
            totals[key] = Decimal(total)
        return totals

    def monthly_cashflow(
        self, user_id: int, date_from: dt.date, date_to: dt.date
    ) -> list[MonthlyCashflowRow]:
        """``GROUP BY`` calendar month - works on SQLite *and* PostgreSQL."""
        month = (
            func.strftime("%Y-%m", Transaction.occurred_on)
            if self._is_sqlite()
            else func.to_char(Transaction.occurred_on, "YYYY-MM")
        )
        income = func.coalesce(
            func.sum(
                case((Transaction.type == TransactionType.INCOME, Transaction.amount), else_=0)
            ),
            0,
        )
        expense = func.coalesce(
            func.sum(
                case((Transaction.type == TransactionType.EXPENSE, Transaction.amount), else_=0)
            ),
            0,
        )

        rows = self.db.execute(
            select(month.label("period"), income.label("income"), expense.label("expense"))
            .where(
                Transaction.user_id == user_id,
                Transaction.occurred_on >= date_from,
                Transaction.occurred_on <= date_to,
            )
            .group_by("period")
            .order_by("period")
            .select_from(Transaction)
        ).all()

        return [
            MonthlyCashflowRow(str(row.period), Decimal(row.income), Decimal(row.expense))
            for row in rows
        ]

    def category_breakdown(
        self, user_id: int, date_from: dt.date, date_to: dt.date, txn_type: TransactionType
    ) -> list[CategoryBreakdownRow]:
        rows = self.db.execute(
            select(
                Transaction.category_id,
                func.coalesce(Category.name, "Uncategorised").label("name"),
                func.coalesce(Category.icon, "❓").label("icon"),
                func.coalesce(Category.color, "#94a3b8").label("color"),
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
                func.count(Transaction.id).label("txn_count"),
            )
            .select_from(Transaction)
            .outerjoin(Category, Category.id == Transaction.category_id)
            .where(
                Transaction.user_id == user_id,
                Transaction.type == txn_type,
                Transaction.occurred_on >= date_from,
                Transaction.occurred_on <= date_to,
            )
            .group_by(Transaction.category_id, Category.name, Category.icon, Category.color)
            .order_by(func.sum(Transaction.amount).desc())
        ).all()

        return [
            CategoryBreakdownRow(
                row.category_id,
                str(row.name),
                str(row.icon),
                str(row.color),
                Decimal(row.total),
                int(row.txn_count),
            )
            for row in rows
        ]

    def merchant_breakdown(
        self, user_id: int, date_from: dt.date, date_to: dt.date, *, limit: int = 10
    ) -> list[MerchantRow]:
        rows = self.db.execute(
            select(
                Transaction.merchant,
                func.sum(Transaction.amount).label("total"),
                func.count(Transaction.id).label("txn_count"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.type == TransactionType.EXPENSE,
                Transaction.merchant.is_not(None),
                Transaction.occurred_on >= date_from,
                Transaction.occurred_on <= date_to,
            )
            .group_by(Transaction.merchant)
            .order_by(func.sum(Transaction.amount).desc())
            .limit(limit)
            .select_from(Transaction)
        ).all()

        return [
            MerchantRow(str(row.merchant), Decimal(row.total), int(row.txn_count)) for row in rows
        ]

    def spend_for_category(
        self, user_id: int, category_id: int, date_from: dt.date, date_to: dt.date
    ) -> Decimal:
        total = self.db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.user_id == user_id,
                Transaction.category_id == category_id,
                Transaction.type == TransactionType.EXPENSE,
                Transaction.occurred_on >= date_from,
                Transaction.occurred_on <= date_to,
            )
        )
        return Decimal(total or 0)

    def top_transactions(
        self, user_id: int, date_from: dt.date, date_to: dt.date, *, limit: int = 10
    ) -> list[TopTransactionRecord]:
        rows = self.db.execute(
            select(
                Transaction.id,
                Transaction.description,
                Transaction.amount,
                Transaction.occurred_on,
                func.coalesce(Category.name, None).label("category"),
                Account.name.label("account"),
                Transaction.type,
            )
            .select_from(Transaction)
            .join(Account, Account.id == Transaction.account_id)
            .outerjoin(Category, Category.id == Transaction.category_id)
            .where(
                Transaction.user_id == user_id,
                Transaction.type == TransactionType.EXPENSE,
                Transaction.occurred_on >= date_from,
                Transaction.occurred_on <= date_to,
            )
            .order_by(Transaction.amount.desc())
            .limit(limit)
        ).all()

        return [
            TopTransactionRecord(
                int(row.id),
                str(row.description),
                Decimal(row.amount),
                row.occurred_on,
                row.category,
                str(row.account),
                row.type,
            )
            for row in rows
        ]

    def distinct_merchants(self, user_id: int, *, limit: int = 500) -> list[str]:
        rows = self.db.scalars(
            select(Transaction.merchant)
            .where(Transaction.user_id == user_id, Transaction.merchant.is_not(None))
            .distinct()
            .limit(limit)
        ).all()
        return sorted({row for row in rows if row})

    # ------------------------------------------------------------------ #
    def _is_sqlite(self) -> bool:
        return self.db.get_bind().dialect.name == "sqlite"
