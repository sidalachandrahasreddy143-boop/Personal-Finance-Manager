"""Shared schema building blocks.

**Money is serialised as a decimal string** (``"1250.00"``) rather than a JSON
number. JSON numbers are IEEE-754 doubles in most clients, and
``0.1 + 0.2 != 0.3`` is not an acceptable failure mode in a ledger.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

T = TypeVar("T")


def _money_to_str(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


Money = Annotated[
    Decimal,
    PlainSerializer(_money_to_str, return_type=str, when_used="json"),
]

MoneyPositive = Annotated[
    Decimal,
    Field(gt=0, max_digits=16, decimal_places=2),
    PlainSerializer(_money_to_str, return_type=str, when_used="json"),
]

MoneyNonNegative = Annotated[
    Decimal,
    Field(ge=0, max_digits=16, decimal_places=2),
    PlainSerializer(_money_to_str, return_type=str, when_used="json"),
]

Ratio = Annotated[
    Decimal,
    PlainSerializer(lambda v: float(v), return_type=float, when_used="json"),
]


class ORMModel(BaseModel):
    """Base for response models read directly from ORM objects."""

    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    """Generic acknowledgement payload."""

    detail: str
    meta: dict[str, Any] | None = None


class ErrorField(BaseModel):
    field: str
    message: str
    type: str


class ProblemDetail(BaseModel):
    """RFC 7807 problem document returned for every error."""

    type: str
    title: str
    status: int
    detail: str
    code: str
    request_id: str | None = None
    instance: str | None = None
    errors: list[ErrorField] | None = None


class Paginated(BaseModel, Generic[T]):
    """OpenAPI-friendly mirror of :class:`app.core.pagination.Page`."""

    items: list[T]
    total: int
    page: int
    size: int
    pages: int


class HealthStatus(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    uptime_seconds: float
    checked_at: dt.datetime
