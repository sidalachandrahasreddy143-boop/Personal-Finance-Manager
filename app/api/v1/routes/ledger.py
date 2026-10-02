"""Accounts, categories and transactions endpoints."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.api.openapi import ERROR_RESPONSES, not_found
from app.core.deps import CurrentUser, DbSession, Pagination
from app.core.pagination import Page
from app.core.rate_limit import enforce_rate_limit
from app.models.enums import CategoryKind, TransactionType
from app.repositories.transactions import TransactionQuery
from app.schemas.common import Message, Paginated
from app.schemas.ledger import (
    AccountBalance,
    AccountCreate,
    AccountRead,
    AccountUpdate,
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
)
from app.services.categorizer import categorizer
from app.services.ledger import LedgerService

router = APIRouter()

# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #


@router.get(
    "/accounts",
    response_model=list[AccountRead],
    tags=["accounts"],
    summary="List accounts",
    responses=ERROR_RESPONSES,
)
def list_accounts(
    user: CurrentUser,
    db: DbSession,
    include_archived: bool = Query(False, description="Include archived accounts"),
    search: str | None = Query(None, max_length=120, description="Filter by name"),
) -> list[AccountRead]:
    service = LedgerService(db)
    return [
        AccountRead.model_validate(a)
        for a in service.list_accounts(user.id, include_archived=include_archived, search=search)
    ]


@router.get(
    "/accounts/balances",
    response_model=list[AccountBalance],
    tags=["accounts"],
    summary="Accounts with live balances",
    description=(
        "Opening balance plus every income minus every expense, " "computed in one grouped query."
    ),
)
def account_balances(
    user: CurrentUser, db: DbSession, include_archived: bool = Query(False)
) -> list[AccountBalance]:
    return LedgerService(db).account_balances(user.id, include_archived=include_archived)


@router.post(
    "/accounts",
    response_model=AccountRead,
    status_code=status.HTTP_201_CREATED,
    tags=["accounts"],
    summary="Create an account",
    responses=ERROR_RESPONSES,
)
def create_account(payload: AccountCreate, user: CurrentUser, db: DbSession) -> AccountRead:
    return AccountRead.model_validate(LedgerService(db).create_account(user.id, payload))


@router.get(
    "/accounts/{account_id}",
    response_model=AccountRead,
    tags=["accounts"],
    summary="Get one account",
    responses=not_found("Account does not exist"),
)
def get_account(account_id: int, user: CurrentUser, db: DbSession) -> AccountRead:
    return AccountRead.model_validate(LedgerService(db).get_account(user.id, account_id))


@router.patch(
    "/accounts/{account_id}",
    response_model=AccountRead,
    tags=["accounts"],
    summary="Update an account",
    responses=not_found("Account does not exist"),
)
def update_account(
    account_id: int, payload: AccountUpdate, user: CurrentUser, db: DbSession
) -> AccountRead:
    return AccountRead.model_validate(
        LedgerService(db).update_account(user.id, account_id, payload)
    )


@router.delete(
    "/accounts/{account_id}",
    response_model=Message,
    tags=["accounts"],
    summary="Delete an empty account",
    description=(
        "Refuses (409/422) when transactions still reference the account - " "archive it instead."
    ),
    responses=ERROR_RESPONSES,
)
def delete_account(account_id: int, user: CurrentUser, db: DbSession) -> Message:
    LedgerService(db).delete_account(user.id, account_id)
    return Message(detail=f"Account {account_id} deleted")


# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #


@router.get(
    "/categories",
    response_model=list[CategoryRead],
    tags=["categories"],
    summary="List categories",
)
def list_categories(
    user: CurrentUser,
    db: DbSession,
    kind: CategoryKind | None = Query(None, description="income | expense"),
    include_archived: bool = Query(False),
    search: str | None = Query(None, max_length=80),
) -> list[CategoryRead]:
    service = LedgerService(db)
    return [
        CategoryRead.model_validate(c)
        for c in service.list_categories(
            user.id, kind=kind, include_archived=include_archived, search=search
        )
    ]


@router.post(
    "/categories",
    response_model=CategoryRead,
    status_code=status.HTTP_201_CREATED,
    tags=["categories"],
    summary="Create a category",
    responses=ERROR_RESPONSES,
)
def create_category(payload: CategoryCreate, user: CurrentUser, db: DbSession) -> CategoryRead:
    return CategoryRead.model_validate(LedgerService(db).create_category(user.id, payload))


@router.post(
    "/categories/seed-defaults",
    response_model=list[CategoryRead],
    tags=["categories"],
    summary="Add the starter category set",
)
def seed_categories(user: CurrentUser, db: DbSession) -> list[CategoryRead]:
    created = LedgerService(db).seed_default_categories(user.id)
    return [CategoryRead.model_validate(c) for c in created]


@router.patch(
    "/categories/{category_id}",
    response_model=CategoryRead,
    tags=["categories"],
    summary="Update a category",
    responses=not_found("Category does not exist"),
)
def update_category(
    category_id: int, payload: CategoryUpdate, user: CurrentUser, db: DbSession
) -> CategoryRead:
    return CategoryRead.model_validate(
        LedgerService(db).update_category(user.id, category_id, payload)
    )


@router.delete(
    "/categories/{category_id}",
    response_model=Message,
    tags=["categories"],
    summary="Delete an unused category",
    responses=ERROR_RESPONSES,
)
def delete_category(category_id: int, user: CurrentUser, db: DbSession) -> Message:
    LedgerService(db).delete_category(user.id, category_id)
    return Message(detail=f"Category {category_id} deleted")


# --------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------- #


@router.get(
    "/transactions",
    response_model=Paginated[TransactionRead],
    tags=["transactions"],
    summary="Search and filter the ledger",
    description=(
        "Every filter is optional and they compose (AND). `search` matches description, "
        "merchant, notes and tags. Sort by `occurred_on` (default), `amount`, `created_at` "
        "or `description`."
    ),
)
def list_transactions(
    user: CurrentUser,
    db: DbSession,
    pagination: Pagination,
    search: str | None = Query(None, max_length=120),
    account_id: int | None = None,
    category_id: int | None = None,
    txn_type: TransactionType | None = Query(None, alias="type"),
    date_from: dt.date | None = Query(None, alias="from", description="Inclusive start date"),
    date_to: dt.date | None = Query(None, alias="to", description="Inclusive end date"),
    min_amount: Decimal | None = Query(None, ge=0),
    max_amount: Decimal | None = Query(None, ge=0),
    tag: Annotated[list[str] | None, Query(description="Repeat to match all tags")] = None,
    sort: str = Query("occurred_on", pattern="^(occurred_on|amount|created_at|description)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
) -> Paginated[TransactionRead]:
    query = TransactionQuery(
        search=search,
        account_id=account_id,
        category_id=category_id,
        type=txn_type,
        date_from=date_from,
        date_to=date_to,
        min_amount=min_amount,
        max_amount=max_amount,
        tags=tag,
        sort=sort,
        order=order,
    )
    items, total = LedgerService(db).list_transactions(
        user.id, query, offset=pagination.offset, limit=pagination.size
    )
    page = Page[TransactionRead].build(
        [TransactionRead.model_validate(t) for t in items], total, pagination
    )
    return Paginated[TransactionRead](**page.model_dump())


@router.post(
    "/transactions",
    response_model=TransactionRead,
    status_code=status.HTTP_201_CREATED,
    tags=["transactions"],
    summary="Record a transaction",
    description="Amounts are always positive; direction comes from `type`.",
    responses=ERROR_RESPONSES,
)
def create_transaction(
    payload: TransactionCreate, user: CurrentUser, db: DbSession, request: Request
) -> TransactionRead:
    enforce_rate_limit(request)
    return TransactionRead.model_validate(LedgerService(db).create_transaction(user.id, payload))


@router.get(
    "/transactions/suggest-category",
    tags=["transactions"],
    summary="Suggest a category from text",
    description="Deterministic keyword rules - handy for prefilling a form or bulk imports.",
)
def suggest_category(
    description: str = Query(..., min_length=2, max_length=255),
    merchant: str | None = Query(None, max_length=120),
) -> dict[str, object]:
    return {
        "suggested_category": categorizer.suggest(description, merchant),
        "confidence": categorizer.confidence(description, merchant),
    }


@router.get(
    "/transactions/{transaction_id}",
    response_model=TransactionRead,
    tags=["transactions"],
    summary="Get one transaction",
    responses=not_found("Transaction does not exist"),
)
def get_transaction(transaction_id: int, user: CurrentUser, db: DbSession) -> TransactionRead:
    return TransactionRead.model_validate(
        LedgerService(db).get_transaction(user.id, transaction_id)
    )


@router.patch(
    "/transactions/{transaction_id}",
    response_model=TransactionRead,
    tags=["transactions"],
    summary="Update a transaction",
    responses=ERROR_RESPONSES,
)
def update_transaction(
    transaction_id: int, payload: TransactionUpdate, user: CurrentUser, db: DbSession
) -> TransactionRead:
    return TransactionRead.model_validate(
        LedgerService(db).update_transaction(user.id, transaction_id, payload)
    )


@router.delete(
    "/transactions/{transaction_id}",
    response_model=Message,
    tags=["transactions"],
    summary="Delete a transaction",
    responses=not_found("Transaction does not exist"),
)
def delete_transaction(transaction_id: int, user: CurrentUser, db: DbSession) -> Message:
    LedgerService(db).delete_transaction(user.id, transaction_id)
    return Message(detail=f"Transaction {transaction_id} deleted")
