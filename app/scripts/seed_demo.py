"""Seed a demo user with ~6 months of realistic, deterministic sample data.

Usage::

    python -m app.scripts.seed_demo            # create if missing (idempotent)
    python -m app.scripts.seed_demo --reset    # wipe and recreate

The generator lives in :mod:`app.services.sample_data` so the CLI and the
dashboard's *Load sample data* button cannot drift apart.
"""

from __future__ import annotations

import argparse

from sqlalchemy import delete, select

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import Account, Budget, Category, Goal, RecurringRule, Transaction, User
from app.services.sample_data import generate_sample_data


def reset_demo_user(email: str | None = None) -> None:
    """Delete the demo user and everything that belongs to them."""
    email = email or settings.demo_email
    Base.metadata.create_all(bind=engine)  # safe when the DB does not exist yet
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.email == email))
        if user_id is None:
            return
        for model in (Transaction, Budget, Goal, RecurringRule, Category, Account):
            db.execute(delete(model).where(model.user_id == user_id))
        db.execute(delete(User).where(User.id == user_id))
        db.commit()


def seed_demo_data(email: str | None = None, password: str | None = None) -> int:
    """Create the demo user and its sample history. Returns the user id."""
    email = email or settings.demo_email
    password = password or settings.demo_password

    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        existing_id = db.scalar(select(User.id).where(User.email == email))
        if existing_id is not None:
            return int(existing_id)

        user = User(
            email=email,
            hashed_password=hash_password(password),
            full_name="Demo User",
            currency="INR",
        )
        db.add(user)
        db.flush()

        generate_sample_data(db, user.id, months=6)
        db.commit()
        return int(user.id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the demo user and sample data")
    parser.add_argument("--reset", action="store_true", help="Delete and recreate the demo user")
    args = parser.parse_args()

    if args.reset:
        reset_demo_user()

    user_id = seed_demo_data()
    print(
        f"Demo data ready. user_id={user_id}  email={settings.demo_email}  "
        f"password={settings.demo_password}\nDashboard: http://localhost:8000/app"
    )


if __name__ == "__main__":
    main()
