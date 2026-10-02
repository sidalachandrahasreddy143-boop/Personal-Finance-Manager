"""Reporting and analytics: cashflow, breakdowns, net worth, trends."""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models.enums import AccountType, CategoryKind, TransactionType
from app.repositories.accounts import AccountRepository
from app.repositories.transactions import TransactionQuery, TransactionRepository
from app.schemas.reports import (
    AccountTypeBalance,
    CashflowPoint,
    CashflowReport,
    CategoryBreakdown,
    CategoryBreakdownItem,
    MerchantSpend,
    MonthlyTrendPoint,
    NetWorthReport,
    TopTransactionRow,
    TrendReport,
)
from app.services.periods import add_months, month_end, month_sequence, month_start

_CENT = Decimal("0.01")
_ASSET_TYPES = {AccountType.CASH, AccountType.BANK, AccountType.WALLET, AccountType.INVESTMENT}
_LIABILITY_TYPES = {AccountType.CREDIT_CARD, AccountType.LOAN}


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def _pct_change(current: Decimal, previous: Decimal) -> float | None:
    if previous == 0:
        return None
    return round(float((current - previous) / previous * 100), 2)


class ReportService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.transactions = TransactionRepository(db)
        self.accounts = AccountRepository(db)

    # ------------------------------------------------------------------ #
    def cashflow(self, user_id: int, date_from: dt.date, date_to: dt.date) -> CashflowReport:
        totals = self.transactions.sum_by_type(user_id, date_from, date_to)
        income, expense = totals["income"], totals["expense"]
        net = _q(income - expense)

        rows = {
            row[0]: row for row in self.transactions.monthly_cashflow(user_id, date_from, date_to)
        }
        points: list[CashflowPoint] = []
        for bucket in month_sequence(date_from, date_to):
            row = rows.get(bucket)
            bucket_income = _q(Decimal(row[1])) if row else Decimal("0.00")
            bucket_expense = _q(Decimal(row[2])) if row else Decimal("0.00")
            points.append(
                CashflowPoint(
                    period=bucket,
                    period_start=dt.date(int(bucket[:4]), int(bucket[5:7]), 1),
                    income=bucket_income,
                    expense=bucket_expense,
                    net=_q(bucket_income - bucket_expense),
                )
            )

        days = max((date_to - date_from).days + 1, 1)
        savings_rate = float((net / income * 100) if income else Decimal("-100") if expense else 0)

        return CashflowReport(
            date_from=date_from,
            date_to=date_to,
            granularity="month",
            income_total=_q(income),
            expense_total=_q(expense),
            net=net,
            savings_rate=round(savings_rate, 2),
            average_daily_spend=_q(Decimal(expense) / days),
            points=points,
        )

    # ------------------------------------------------------------------ #
    def category_breakdown(
        self,
        user_id: int,
        date_from: dt.date,
        date_to: dt.date,
        *,
        kind: CategoryKind = CategoryKind.EXPENSE,
        compare: bool = True,
    ) -> CategoryBreakdown:
        txn_type = (
            TransactionType.EXPENSE if kind is CategoryKind.EXPENSE else TransactionType.INCOME
        )
        rows = self.transactions.category_breakdown(user_id, date_from, date_to, txn_type)
        total = _q(sum((row.total for row in rows), Decimal("0.00")))

        previous: dict[int | None, Decimal] = {}
        if compare:
            span = (date_to - date_from).days + 1
            prev_rows = self.transactions.category_breakdown(
                user_id,
                date_from - dt.timedelta(days=span),
                date_from - dt.timedelta(days=1),
                txn_type,
            )
            previous = {row.category_id: row.total for row in prev_rows}

        items: list[CategoryBreakdownItem] = []
        for row in rows:
            amount = _q(row.total)
            already = previous.get(row.category_id, Decimal("0.00"))
            items.append(
                CategoryBreakdownItem(
                    category_id=row.category_id,
                    name=row.name,
                    icon=row.icon,
                    color=row.color,
                    total=amount,
                    share_pct=round(float(amount / total * 100), 2) if total else 0.0,
                    transaction_count=row.transaction_count,
                    average_amount=_q(amount / row.transaction_count)
                    if row.transaction_count
                    else Decimal("0.00"),
                    previous_total=_q(already),
                    change_pct=_pct_change(amount, already),
                )
            )

        return CategoryBreakdown(
            kind=kind, date_from=date_from, date_to=date_to, total=total, items=items
        )

    # ------------------------------------------------------------------ #
    def merchants(
        self, user_id: int, date_from: dt.date, date_to: dt.date, *, limit: int = 10
    ) -> list[MerchantSpend]:
        rows = self.transactions.merchant_breakdown(user_id, date_from, date_to, limit=limit)
        return [
            MerchantSpend(
                merchant=row.merchant,
                total=_q(row.total),
                transaction_count=row.transaction_count,
                average_amount=_q(row.total / row.transaction_count)
                if row.transaction_count
                else Decimal("0.00"),
            )
            for row in rows
        ]

    # ------------------------------------------------------------------ #
    def net_worth(self, user_id: int, *, as_of: dt.date | None = None) -> NetWorthReport:
        accounts = self.accounts.list_for_user(user_id, include_archived=False)
        totals = self.accounts.totals_by_account(user_id)

        per_type: dict[AccountType, list[Decimal]] = {}
        assets = Decimal("0.00")
        liabilities = Decimal("0.00")

        for account in accounts:
            agg = totals.get(account.id)
            balance = Decimal(account.opening_balance)
            if agg:
                balance += agg.income - agg.expense

            if account.type in _ASSET_TYPES and balance > 0:
                assets += balance
            elif balance < 0:
                liabilities += -balance

            per_type.setdefault(account.type, []).append(balance)

        by_type = [
            AccountTypeBalance(
                type=account_type,
                balance=_q(sum(balances, Decimal("0.00"))),
                account_count=len(balances),
            )
            for account_type, balances in sorted(per_type.items(), key=lambda item: item[0].value)
        ]

        return NetWorthReport(
            as_of=as_of or dt.date.today(),
            assets=_q(assets),
            liabilities=_q(liabilities),
            net_worth=_q(assets - liabilities),
            by_type=by_type,
        )

    # ------------------------------------------------------------------ #
    def trends(self, user_id: int, *, months: int = 6, as_of: dt.date | None = None) -> TrendReport:
        reference = as_of or dt.date.today()
        end = month_end(reference)
        start = month_start(add_months(reference, -(months - 1)))

        rows = {row[0]: row for row in self.transactions.monthly_cashflow(user_id, start, end)}

        points: list[MonthlyTrendPoint] = []
        for bucket in month_sequence(start, end):
            row = rows.get(bucket)
            income = _q(row.income) if row else Decimal("0.00")
            expense = _q(row.expense) if row else Decimal("0.00")
            net = _q(income - expense)
            points.append(
                MonthlyTrendPoint(
                    month=bucket,
                    income=income,
                    expense=expense,
                    net=net,
                    savings_rate=round(float(net / income * 100), 2) if income else 0.0,
                )
            )

        best = max(points, key=lambda p: p.net, default=None)
        worst = min(points, key=lambda p: p.net, default=None)
        divisor = len(points) or 1

        return TrendReport(
            months=points,
            best_month=best.month if best else None,
            worst_month=worst.month if worst else None,
            average_monthly_income=_q(sum((p.income for p in points), Decimal("0.00")) / divisor),
            average_monthly_expense=_q(sum((p.expense for p in points), Decimal("0.00")) / divisor),
        )

    # ------------------------------------------------------------------ #
    def top_transactions(
        self, user_id: int, date_from: dt.date, date_to: dt.date, *, limit: int = 10
    ) -> list[TopTransactionRow]:
        rows = self.transactions.top_transactions(user_id, date_from, date_to, limit=limit)
        return [
            TopTransactionRow(
                id=row.id,
                description=row.description,
                amount=_q(row.amount),
                occurred_on=row.occurred_on,
                category=row.category,
                account=row.account,
                type=row.type,
            )
            for row in rows
        ]

    # ------------------------------------------------------------------ #
    def largest_expense(self, user_id: int, date_from: dt.date, date_to: dt.date) -> Decimal:
        rows = self.transactions.top_transactions(user_id, date_from, date_to, limit=1)
        return _q(rows[0].amount) if rows else Decimal("0.00")

    def count_transactions(self, user_id: int, date_from: dt.date, date_to: dt.date) -> int:
        return self.transactions.count(
            self.transactions.build_query(
                user_id, TransactionQuery(date_from=date_from, date_to=date_to)
            )
        )
