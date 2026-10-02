"""Generic repository helpers.

Repositories own *all* SQLAlchemy access. Services and routers never build a
query, which keeps the web layer testable and refactors local.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """CRUD primitives shared by every repository."""

    model: type[ModelT]

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- reads -------------------------------------------------------------
    def get(self, obj_id: int) -> ModelT | None:
        return self.db.get(self.model, obj_id)

    def get_or_404(self, obj_id: int, *, name: str | None = None) -> ModelT:
        obj = self.get(obj_id)
        if obj is None:
            raise NotFoundError(f"{name or self.model.__name__} {obj_id} does not exist")
        return obj

    def count(self, statement: Select[Any] | None = None) -> int:
        stmt = statement if statement is not None else select(self.model)
        return int(self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)

    # --- writes ------------------------------------------------------------
    def create(self, **values: Any) -> ModelT:
        obj = self.model(**values)
        self.db.add(obj)
        self.db.flush()
        self.db.refresh(obj)
        return obj

    def update(self, obj: ModelT, **values: Any) -> ModelT:
        for key, value in values.items():
            if value is not None:
                setattr(obj, key, value)
        self.db.flush()
        self.db.refresh(obj)
        return obj

    def delete(self, obj: ModelT) -> None:
        self.db.delete(obj)
        self.db.flush()

    def paginate(self, stmt: Select[Any], offset: int, limit: int) -> tuple[list[ModelT], int]:
        """Return one page of results plus the unpaginated total count."""
        total = self.count(stmt)
        items = list(self.db.scalars(stmt.offset(offset).limit(limit)).unique().all())
        return items, total
