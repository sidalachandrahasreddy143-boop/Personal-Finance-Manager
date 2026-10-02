"""User data access."""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.security import hash_password
from app.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    def get_by_email(self, email: str) -> User | None:
        """Case-insensitive lookup; emails are normalised on write."""
        return self.db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))

    def create_user(
        self, *, email: str, password: str, full_name: str | None = None, currency: str = "INR"
    ) -> User:
        return self.create(
            email=email.strip().lower(),
            hashed_password=hash_password(password),
            full_name=full_name,
            currency=currency,
        )

    def set_password(self, user: User, new_password: str) -> User:
        user.hashed_password = hash_password(new_password)
        self.db.flush()
        return user
