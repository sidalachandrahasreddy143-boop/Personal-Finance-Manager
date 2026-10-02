"""Cron / worker entry point: post every due recurring transaction for all users.

Example crontab (06:00 daily)::

    0 6 * * *  cd /srv/pfm && .venv/bin/python -m app.scripts.run_recurring

The API itself is stateless; scheduling lives here or in your orchestrator.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import User
from app.services.periods import today_utc
from app.services.recurring import RecurringService

logger = logging.getLogger(__name__)


def run(as_of: dt.date | None = None) -> int:
    """Post all due transactions for every active user. Returns the count posted."""
    reference = as_of or today_utc()
    posted_total = 0

    with SessionLocal() as db:
        user_ids = list(db.scalars(select(User.id).where(User.is_active.is_(True))).all())
        service = RecurringService(db)
        for user_id in user_ids:
            posted = service.run_due(user_id, as_of=reference)
            if posted:
                logger.info("Posted %s recurring transaction(s) for user %s", len(posted), user_id)
            posted_total += len(posted)
        db.commit()

    logger.info(
        "Recurring run complete: %s transaction(s) posted for %s user(s)",
        posted_total,
        len(user_ids),
    )
    return posted_total


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Post due recurring transactions")
    parser.add_argument("--as-of", type=dt.date.fromisoformat, default=None)
    args = parser.parse_args()
    print(f"Posted {run(args.as_of)} transaction(s)")


if __name__ == "__main__":
    main()
