"""Accounts, categories and transactions - the write-side business logic."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.models import Account, Category, Transaction
from app.models.enums import CategoryKind, TransactionType
from app.repositories.accounts import AccountRepository
from app.repositories.categories import CategoryRepository
from app.repositories.transactions import TransactionQuery, TransactionRepository
from app.schemas.ledger import (
    AccountBalance,
    AccountCreate,
    AccountUpdate,
    CategoryCreate,
    CategoryUpdate,
    TransactionCreate,
    TransactionUpdate,
)

_EXPECTED_KIND = {
    TransactionType.INCOME: CategoryKind.INCOME,
    TransactionType.EXPENSE: CategoryKind.EXPENSE,
}


class LedgerService:
    """Coordinates accounts, categories and transactions."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.accounts = AccountRepository(db)
        self.categories = CategoryRepository(db)
        self.transactions = TransactionRepository(db)

    # ------------------------------------------------------------------ #
    # Accounts
    # ------------------------------------------------------------------ #
    def create_account(self, user_id: int, payload: AccountCreate) -> Account:
        if self.accounts.name_exists(user_id, payload.name):
            raise ConflictError(f"You already have an account named '{payload.name}'")
        return self.accounts.create(user_id=user_id, **payload.model_dump())

    def list_accounts(
        self, user_id: int, *, include_archived: bool = False, search: str | None = None
    ) -> list[Account]:
        return self.accounts.list_for_user(
            user_id, include_archived=include_archived, search=search
        )

    def get_account(self, user_id: int, account_id: int) -> Account:
        return self.accounts.get_for_user(user_id, account_id)

    def update_account(self, user_id: int, account_id: int, payload: AccountUpdate) -> Account:
        account = self.accounts.get_for_user(user_id, account_id)
        if payload.name and self.accounts.name_exists(user_id, payload.name, exclude_id=account_id):
            raise ConflictError(f"You already have an account named '{payload.name}'")
        return self.accounts.update(account, **payload.model_dump(exclude_unset=True))

    def delete_account(self, user_id: int, account_id: int) -> None:
        account = self.accounts.get_for_user(user_id, account_id)
        totals = self.accounts.totals_for_account(user_id, account_id)
        if totals.transaction_count:
            raise BusinessRuleError(
                f"'{account.name}' still has {totals.transaction_count} transaction(s). "
                "Archive it instead, or move the transactions first.",
                extra={"transaction_count": totals.transaction_count},
            )
        self.accounts.delete(account)

    def account_balances(
        self, user_id: int, *, include_archived: bool = False
    ) -> list[AccountBalance]:
        accounts = self.accounts.list_for_user(user_id, include_archived=include_archived)
        totals = self.accounts.totals_by_account(user_id)
        result: list[AccountBalance] = []
        for account in accounts:
            agg = totals.get(account.id)
            income = agg.income if agg else Decimal("0.00")
            expense = agg.expense if agg else Decimal("0.00")
            result.append(
                AccountBalance(
                    account=account,
                    current_balance=Decimal(account.opening_balance) + income - expense,
                    income_total=income,
                    expense_total=expense,
                    transaction_count=agg.transaction_count if agg else 0,
                )
            )
        return result

    # ------------------------------------------------------------------ #
    # Categories
    # ------------------------------------------------------------------ #
    def create_category(self, user_id: int, payload: CategoryCreate) -> Category:
        if self.categories.name_taken(user_id, payload.name, payload.kind):
            raise ConflictError(
                f"A {payload.kind.value} category named '{payload.name}' already exists"
            )
        return self.categories.create(user_id=user_id, **payload.model_dump())

    def list_categories(
        self,
        user_id: int,
        *,
        kind: CategoryKind | None = None,
        include_archived: bool = False,
        search: str | None = None,
    ) -> list[Category]:
        return self.categories.list_for_user(
            user_id, kind=kind, include_archived=include_archived, search=search
        )

    def get_category(self, user_id: int, category_id: int) -> Category:
        return self.categories.get_for_user(user_id, category_id)

    def update_category(self, user_id: int, category_id: int, payload: CategoryUpdate) -> Category:
        category = self.categories.get_for_user(user_id, category_id)
        if payload.name and self.categories.name_taken(
            user_id, payload.name, category.kind, exclude_id=category_id
        ):
            raise ConflictError(f"A category named '{payload.name}' already exists")
        return self.categories.update(category, **payload.model_dump(exclude_unset=True))

    def delete_category(self, user_id: int, category_id: int) -> None:
        category = self.categories.get_for_user(user_id, category_id)
        used = self.transactions.count(
            self.transactions.build_query(
                user_id, TransactionQuery(category_id=category_id, sort="created_at")
            )
        )
        if used:
            raise BusinessRuleError(
                f"'{category.name}' is used by {used} transaction(s). "
                "Archive it to hide it from pickers without losing history.",
                extra={"transaction_count": used},
            )
        self.categories.delete(category)

    def seed_default_categories(self, user_id: int) -> list[Category]:
        return self.categories.seed_defaults(user_id)

    # ------------------------------------------------------------------ #
    # Transactions
    # ------------------------------------------------------------------ #
    def create_transaction(self, user_id: int, payload: TransactionCreate) -> Transaction:
        account = self.accounts.get_for_user(user_id, payload.account_id)
        category = self._resolve_category(user_id, payload.category_id, payload.type)

        txn = self.transactions.create(
            user_id=user_id,
            account_id=account.id,
            category_id=category.id if category else None,
            type=payload.type,
            amount=payload.amount,
            currency=account.currency,
            description=payload.description,
            merchant=payload.merchant,
            occurred_on=payload.occurred_on,
            notes=payload.notes,
            tags=",".join(payload.tags) if payload.tags else None,
            is_recurring=payload.is_recurring,
        )
        return txn

    def list_transactions(
        self, user_id: int, query: TransactionQuery, *, offset: int, limit: int
    ) -> tuple[list[Transaction], int]:
        return self.transactions.list_for_user(user_id, query, offset=offset, limit=limit)

    def get_transaction(self, user_id: int, transaction_id: int) -> Transaction:
        return self.transactions.get_for_user(user_id, transaction_id)

    def update_transaction(
        self, user_id: int, transaction_id: int, payload: TransactionUpdate
    ) -> Transaction:
        txn = self.transactions.get_for_user(user_id, transaction_id)
        data = payload.model_dump(exclude_unset=True)

        new_type = data.get("type", txn.type)
        if "account_id" in data and data["account_id"] is not None:
            self.accounts.get_for_user(user_id, data["account_id"])

        if "category_id" in data:
            category = self._resolve_category(user_id, data["category_id"], new_type)
            txn.category_id = category.id if category else None
        elif new_type != txn.type and txn.category_id is not None:
            # Type flipped (expense -> income): the old category no longer fits.
            category = self.categories.get_for_user(user_id, txn.category_id)
            if category.kind is not _EXPECTED_KIND[new_type]:
                raise BusinessRuleError(
                    f"Category '{category.name}' is a {category.kind.value} category and cannot be "
                    f"used for a {new_type.value} transaction. Pass a matching category_id."
                )

        data.pop("category_id", None)
        if "tags" in data:
            tags = data.pop("tags") or []
            txn.tags = ",".join(tags) if tags else None

        if data.get("type") == TransactionType.TRANSFER and "amount" in data:
            pass  # transfers keep ledger symmetry; amount stays positive

        return self.transactions.update(txn, **data)

    def delete_transaction(self, user_id: int, transaction_id: int) -> None:
        txn = self.transactions.get_for_user(user_id, transaction_id)
        self.transactions.delete(txn)

    # ------------------------------------------------------------------ #
    def _resolve_category(
        self, user_id: int, category_id: int | None, txn_type: TransactionType
    ) -> Category | None:
        if category_id is None:
            return None
        category = self.categories.get_for_user(user_id, category_id)
        expected = _EXPECTED_KIND.get(txn_type)
        if expected is not None and category.kind is not expected:
            raise BusinessRuleError(
                f"Category '{category.name}' is a {category.kind.value} category; "
                f"a {txn_type.value} transaction needs a {expected.value} category."
            )
        if category.is_archived:
            raise BusinessRuleError(f"Category '{category.name}' is archived")
        if txn_type is TransactionType.TRANSFER and category.kind is CategoryKind.INCOME:
            raise BusinessRuleError("Transfers cannot use an income category")
        return category


def ensure_owned_category(db: Session, user_id: int, category_id: int) -> Category:
    """Small helper reused by services that only need the ownership check."""
    category = CategoryRepository(db).get(category_id)
    if category is None or category.user_id != user_id:
        raise NotFoundError(f"Category {category_id} does not exist")
    return category
