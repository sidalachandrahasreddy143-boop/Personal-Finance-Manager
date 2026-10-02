"""Category data access."""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.errors import NotFoundError
from app.models import Category
from app.models.enums import CategoryKind
from app.repositories.base import BaseRepository

DEFAULT_CATEGORIES: list[tuple[str, CategoryKind, str, str]] = [
    # (name, kind, color, icon)
    ("Salary", CategoryKind.INCOME, "#16a34a", "💰"),
    ("Freelance", CategoryKind.INCOME, "#22c55e", "🧑‍💻"),
    ("Investments", CategoryKind.INCOME, "#0ea5e9", "📈"),
    ("Rent", CategoryKind.EXPENSE, "#ef4444", "🏠"),
    ("Groceries", CategoryKind.EXPENSE, "#f97316", "🛒"),
    ("Transport", CategoryKind.EXPENSE, "#eab308", "🚕"),
    ("Dining", CategoryKind.EXPENSE, "#ec4899", "🍽️"),
    ("Utilities", CategoryKind.EXPENSE, "#6366f1", "💡"),
    ("Health", CategoryKind.EXPENSE, "#14b8a6", "🩺"),
    ("Shopping", CategoryKind.EXPENSE, "#a855f7", "🛍️"),
    ("Entertainment", CategoryKind.EXPENSE, "#f43f5e", "🎬"),
    ("Education", CategoryKind.EXPENSE, "#3b82f6", "📚"),
]


class CategoryRepository(BaseRepository[Category]):
    model = Category

    def list_for_user(
        self,
        user_id: int,
        *,
        kind: CategoryKind | None = None,
        include_archived: bool = False,
        search: str | None = None,
    ) -> list[Category]:
        stmt = select(Category).where(Category.user_id == user_id)
        if kind is not None:
            stmt = stmt.where(Category.kind == kind)
        if not include_archived:
            stmt = stmt.where(Category.is_archived.is_(False))
        if search:
            stmt = stmt.where(Category.name.ilike(f"%{search}%"))
        return list(self.db.scalars(stmt.order_by(Category.kind.asc(), Category.name.asc())).all())

    def get_for_user(self, user_id: int, category_id: int) -> Category:
        category = self.db.scalar(
            select(Category).where(Category.id == category_id, Category.user_id == user_id)
        )
        if category is None:
            raise NotFoundError(f"Category {category_id} does not exist")
        return category

    def find_by_name(self, user_id: int, name: str, kind: CategoryKind) -> Category | None:
        return self.db.scalar(
            select(Category).where(
                Category.user_id == user_id,
                Category.kind == kind,
                func.lower(Category.name) == name.strip().lower(),
            )
        )

    def name_taken(
        self, user_id: int, name: str, kind: CategoryKind, *, exclude_id: int | None = None
    ) -> bool:
        stmt = select(func.count(Category.id)).where(
            Category.user_id == user_id,
            Category.kind == kind,
            func.lower(Category.name) == name.strip().lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(Category.id != exclude_id)
        return bool(self.db.scalar(stmt))

    def seed_defaults(self, user_id: int) -> list[Category]:
        """Give a brand-new user a sensible starting set of categories."""
        created: list[Category] = []
        for name, kind, color, icon in DEFAULT_CATEGORIES:
            existing = self.find_by_name(user_id, name, kind)
            if existing is None:
                created.append(
                    self.create(user_id=user_id, name=name, kind=kind, color=color, icon=icon)
                )
        return created

    def counts_by_name(self, user_id: int) -> dict[str, Category]:
        rows = self.db.scalars(select(Category).where(Category.user_id == user_id)).all()
        return {c.name.lower(): c for c in rows}
