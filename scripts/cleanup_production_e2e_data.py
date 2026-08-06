"""Delete stale production E2E threads for the dedicated automation account."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.database import AsyncSessionLocal, async_engine
from app.models.thread import Thread
from app.models.user import User

E2E_TITLE_PATTERN = re.compile(r"^\[E2E\] [A-Za-z0-9._-]+ .+")
DEFAULT_MAX_AGE_HOURS = 24


@dataclass(frozen=True)
class CleanupResult:
    """Sanitized cleanup result suitable for logs and workflow summaries."""

    account_found: bool
    cutoff: str
    deleted_count: int
    dry_run: bool


def is_managed_e2e_title(title: str) -> bool:
    """Return whether a title follows the production E2E ownership convention.

    Args:
        title: Thread title to validate.

    Returns:
        True only for the strict ``[E2E] <run-id> <description>`` format.
    """
    return E2E_TITLE_PATTERN.fullmatch(title) is not None


async def cleanup_stale_threads(
    *,
    account_email: str,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    dry_run: bool = False,
    now: datetime | None = None,
) -> CleanupResult:
    """Delete stale, unmistakably test-owned threads for one account.

    Args:
        account_email: Exact email of the dedicated production E2E account.
        max_age_hours: Minimum thread age before deletion.
        dry_run: Report candidates without deleting them.
        now: Optional deterministic clock for tests.

    Returns:
        Sanitized cleanup result without titles, IDs, or account data.

    Raises:
        ValueError: If the account email or age boundary is invalid.
    """
    normalized_email = account_email.strip().lower()
    if not normalized_email:
        raise ValueError("account_email must not be empty")
    if max_age_hours < 1:
        raise ValueError("max_age_hours must be at least 1")

    cutoff = (now or datetime.now(UTC)) - timedelta(hours=max_age_hours)

    async with AsyncSessionLocal() as session:
        user_id = await session.scalar(
            select(User.id).where(User.email == normalized_email)
        )
        if user_id is None:
            return CleanupResult(
                account_found=False,
                cutoff=cutoff.isoformat(),
                deleted_count=0,
                dry_run=dry_run,
            )

        candidate_rows = (
            await session.execute(
                select(Thread.id, Thread.title)
                .where(Thread.user_id == user_id)
                .where(Thread.is_test.is_(True))
                .where(Thread.created_at < cutoff)
            )
        ).all()
        candidate_ids = [
            thread_id
            for thread_id, title in candidate_rows
            if is_managed_e2e_title(title)
        ]

        if candidate_ids and not dry_run:
            await session.execute(
                delete(Thread)
                .where(Thread.user_id == user_id)
                .where(Thread.id.in_(candidate_ids))
            )
            await session.commit()

        return CleanupResult(
            account_found=True,
            cutoff=cutoff.isoformat(),
            deleted_count=len(candidate_ids),
            dry_run=dry_run,
        )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed janitor arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--account-email",
        default=os.getenv("PROD_E2E_ACCOUNT_EMAIL", ""),
        help="Dedicated production E2E account email",
    )
    parser.add_argument(
        "--max-age-hours",
        type=int,
        default=DEFAULT_MAX_AGE_HOURS,
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def _main() -> int:
    args = parse_args()
    try:
        result = await cleanup_stale_threads(
            account_email=args.account_email,
            max_age_hours=args.max_age_hours,
            dry_run=args.dry_run,
        )
        print(json.dumps(asdict(result), sort_keys=True))
        if not result.account_found:
            print("Dedicated production E2E account was not found.")
            return 2
        return 0
    finally:
        await async_engine.dispose()


def main() -> int:
    """Run the production E2E janitor.

    Returns:
        Process exit code.
    """
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
