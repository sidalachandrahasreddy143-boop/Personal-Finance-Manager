"""Domain enumerations shared by models, schemas and services."""

from __future__ import annotations

from enum import StrEnum


class AccountType(StrEnum):
    CASH = "cash"
    BANK = "bank"
    CREDIT_CARD = "credit_card"
    WALLET = "wallet"
    INVESTMENT = "investment"
    LOAN = "loan"


class CategoryKind(StrEnum):
    """Categories are either money coming in or money going out."""

    INCOME = "income"
    EXPENSE = "expense"


class TransactionType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"


class BudgetPeriod(StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class GoalStatus(StrEnum):
    ACTIVE = "active"
    ACHIEVED = "achieved"
    ARCHIVED = "archived"


class Frequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
