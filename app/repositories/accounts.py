"""Account data access, including live balance aggregation."""

from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import case, func, select

from app.core.errors import NotFoundError
from app.models import Account, Transaction
from app.models.enums import AccountType, TransactionType
from app.repositories.base import BaseRepository


class AccountTotals(NamedTuple):
    """Aggregated income/expense for one account.

    ``transaction_count`` rather than ``count`` - a NamedTuple field named
    ``count`` would shadow ``tuple.count``.
    """

    income: Decimal
    expense: Decimal
    transaction_count: int

    @property
    def net(self) -> Decimal:
        return self.income - self.expense


class AccountRepository(BaseRepository[Account]):
    model = Account

    def list_for_user(
        self, user_id: int, *, include_archived: bool = False, search: str | None = None
    ) -> list[Account]:
        stmt = select(Account).where(Account.user_id == user_id)
        if not include_archived:
            stmt = stmt.where(Account.is_archived.is_(False))
        if search:
            stmt = stmt.where(Account.name.ilike(f"%{search}%"))
        return list(self.db.scalars(stmt.order_by(Account.created_at.asc())).all())

    def get_for_user(self, user_id: int, account_id: int) -> Account:
        account = self.db.scalar(
            select(Account).where(Account.id == account_id, Account.user_id == user_id)
        )
        if account is None:
            raise NotFoundError(f"Account {account_id} does not exist")
        return account

    def name_exists(self, user_id: int, name: str, *, exclude_id: int | None = None) -> bool:
        stmt = select(func.count(Account.id)).where(
            Account.user_id == user_id, func.lower(Account.name) == name.strip().lower()
        )
        if exclude_id is not None:
            stmt = stmt.where(Account.id != exclude_id)
        return bool(self.db.scalar(stmt))

    def totals_for_account(self, user_id: int, account_id: int) -> AccountTotals:
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
        row = self.db.execute(
            select(income, expense, func.count(Transaction.id))
            .where(Transaction.user_id == user_id, Transaction.account_id == account_id)
            .select_from(Transaction)
        ).one()
        return AccountTotals(
            income=Decimal(row[0]), expense=Decimal(row[1]), transaction_count=int(row[2])
        )

    def totals_by_account(self, user_id: int) -> dict[int, AccountTotals]:
        """Batch version used by the accounts list (avoids N+1 queries)."""
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
            select(Transaction.account_id, income, expense, func.count(Transaction.id))
            .where(Transaction.user_id == user_id)
            .group_by(Transaction.account_id)
            .select_from(Transaction)
        ).all()
        return {
            int(row[0]): AccountTotals(Decimal(row[1]), Decimal(row[2]), int(row[3]))
            for row in rows
        }

    def balance_by_type(self, user_id: int) -> list[tuple[AccountType, Decimal, int]]:
        """Aggregate opening balances per account type (transactions added by caller)."""
        rows = self.db.execute(
            select(
                Account.type,
                func.coalesce(func.sum(Account.opening_balance), 0),
                func.count(Account.id),
            )
            .where(Account.user_id == user_id, Account.is_archived.is_(False))
            .group_by(Account.type)
            .select_from(Account)
        ).all()
        return [(row[0], Decimal(row[1]), int(row[2])) for row in rows]
