"""Aggregate router for API v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import auth, budgets, data, goals, insights, ledger, meta, recurring, reports

api_router = APIRouter()

# Order matters only for readability here - every router owns a distinct prefix.
api_router.include_router(meta.router)
api_router.include_router(auth.router)
api_router.include_router(ledger.router)
api_router.include_router(budgets.router)
api_router.include_router(goals.router)
api_router.include_router(recurring.router)
api_router.include_router(reports.router)
api_router.include_router(insights.router)
api_router.include_router(data.router)
