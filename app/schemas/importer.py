"""CSV import / export schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ImportRowError(BaseModel):
    row: int = Field(description="1-based line number in the uploaded file")
    error: str


class ImportSummary(BaseModel):
    imported: int
    skipped: int
    total_rows: int
    created_accounts: list[str]
    created_categories: list[str]
    errors: list[ImportRowError]
    dry_run: bool
