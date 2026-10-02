"""Application settings, loaded from environment variables (12-factor style).

Every setting can be overridden with a ``PFM_``-prefixed environment variable,
e.g. ``PFM_DATABASE_URL=postgresql+psycopg://...``.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application configuration."""

    model_config = SettingsConfigDict(
        env_prefix="PFM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "Personal Finance Manager API"
    app_version: str = "1.0.0"
    environment: Literal["development", "staging", "production", "test"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # --- Security ---
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 120
    bcrypt_rounds: int = 12

    # --- Database ---
    database_url: str = "sqlite:///./pfm.db"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # --- CORS ---
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"]
    )

    # --- Rate limiting ---
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 10

    # --- Locale / money ---
    default_currency: str = "INR"
    default_timezone: str = "Asia/Kolkata"

    # --- Demo data ---
    seed_demo_user: bool = False
    demo_email: str = "demo@pfm.app"
    demo_password: str = "demo1234"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Allow ``PFM_CORS_ORIGINS=a,b,c`` as well as a JSON list."""
        if isinstance(value, str) and not value.strip().startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("secret_key")
    @classmethod
    def _reject_placeholder_secret(cls, value: str) -> str:
        if value in {"change-me-in-production-openssl-rand-hex-32", "changeme", "secret"}:
            raise ValueError(
                "PFM_SECRET_KEY is still set to a placeholder. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton (cached for performance)."""
    return Settings()


settings = get_settings()
