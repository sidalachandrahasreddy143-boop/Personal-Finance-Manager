"""SQLAlchemy ORM models.

Importing this package registers every model on ``Base.metadata`` so that
Alembic autogenerate and ``create_all`` see the full schema.
"""

from app.models.account import Account
from app.models.budget import Budget
from app.models.category import Category
from app.models.goal import Goal
from app.models.recurring import RecurringRule
from app.models.transaction import Transaction
from app.models.user import User

__all__ = [
    "Account",
    "Budget",
    "Category",
    "Goal",
    "RecurringRule",
    "Transaction",
    "User",
]
