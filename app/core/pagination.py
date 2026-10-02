"""Reusable pagination primitives."""

from __future__ import annotations

import math
from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

T = TypeVar("T")


class PageParams(BaseModel):
    """Query-string pagination input."""

    page: int = Field(default=1, ge=1, description="1-based page number")
    size: int = Field(default=25, ge=1, le=200, description="Items per page (max 200)")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


def page_params(
    page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
    size: Annotated[int, Query(ge=1, le=200, description="Items per page")] = 25,
) -> PageParams:
    """FastAPI dependency for pagination query parameters."""
    return PageParams(page=page, size=size)


class Page(BaseModel, Generic[T]):
    """A page of results plus the metadata a UI needs to render controls."""

    items: list[T]
    total: int = Field(description="Total rows matching the query")
    page: int
    size: int
    pages: int

    @classmethod
    def build(cls, items: list[T], total: int, params: PageParams) -> Page[T]:
        return cls(
            items=items,
            total=total,
            page=params.page,
            size=params.size,
            pages=max(1, math.ceil(total / params.size)) if total else 0,
        )
