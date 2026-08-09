"""Delete disposable production E2E accounts behind strict ownership guards."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, async_engine
from app.models.continuity_rule import ContinuityRule
from app.models.dependency_group import DependencyGroup
from app.models.reading_order import ReadingOrder
from app.models.thread import Thread
from app.models.user import User

DEFAULT_MAX_AGE_HOURS = 24
E2E_USERNAME_PATTERN = re.compile(r"^e2e_(?P<run_id>[0-9]+)_(?P<attempt>[0-9]+)$")
E2E_EMAIL_PATTERN = re.compile(
    r"^comicpile-e2e\+(?P<run_id>[0-9]+)\.(?P<attempt>[0-9]+)@example\.com$"
)


@dataclass(frozen=True)
class CleanupResult:
    """Sanitized cleanup result suitable for workflow logs."""

    candidate_count: int
    cutoff: str | None
    deleted_count: int
    dry_run: bool
    refused_count: int


def is_managed_e2e_account(username: str, email: str | None) -> bool:
    """Return whether both identifiers encode the same GitHub run.

    Args:
        username: Candidate account username.
        email: Candidate account email.

    Returns:
        True only for the reserved, matching run-scoped identifier pair.
    """
    username_match = E2E_USERNAME_PATTERN.fullmatch(username)
    email_match = E2E_EMAIL_PATTERN.fullmatch(email or "")
    if username_match is None or email_match is None:
        return False
    return username_match.groupdict() == email_match.groupdict()


async def _owns_application_data(session: AsyncSession, user_id: int) -> bool:
    """Return whether deleting an account could remove user-created data."""
    models = (Thread, ReadingOrder, DependencyGroup, ContinuityRule)
    for model in models:
        count = await session.scalar(
            select(func.count()).select_from(model).where(model.user_id == user_id)
        )
        if count:
            return True
    return False


async def cleanup_e2e_accounts(
    *,
    account_username: str | None = None,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    dry_run: bool = False,
    now: datetime | None = None,
) -> CleanupResult:
    """Delete exact or stale disposable accounts that contain no application data.

    Args:
        account_username: Exact current-run username, or None for stale cleanup.
        max_age_hours: Minimum age used by stale cleanup.
        dry_run: Report eligible accounts without deleting them.
        now: Optional deterministic clock for tests.

    Returns:
        Sanitized counts without account identifiers.

    Raises:
        ValueError: If an identifier or age boundary is invalid.
    """
    normalized_username = account_username.strip() if account_username else None
    if account_username is not None and not normalized_username:
        raise ValueError("account_username must not be empty")
    if normalized_username and E2E_USERNAME_PATTERN.fullmatch(normalized_username) is None:
        raise ValueError("account_username is outside the managed E2E namespace")
    if max_age_hours < 1:
        raise ValueError("max_age_hours must be at least 1")

    cutoff = None
    if normalized_username is None:
        cutoff = (now or datetime.now(UTC)) - timedelta(hours=max_age_hours)

    async with AsyncSessionLocal() as session:
        query = select(User).with_for_update()
        if normalized_username is not None:
            query = query.where(User.username == normalized_username)
        else:
            query = query.where(User.username.startswith("e2e_", autoescape=True))
            query = query.where(User.created_at < cutoff)

        candidates = list((await session.scalars(query)).all())
        managed = [
            user for user in candidates if is_managed_e2e_account(user.username, user.email)
        ]
        refused_count = 0
        deletable: list[User] = []
        for user in managed:
            if await _owns_application_data(session, user.id):
                refused_count += 1
            else:
                deletable.append(user)

        if deletable and not dry_run:
            await session.execute(delete(User).where(User.id.in_([user.id for user in deletable])))
            await session.commit()

        return CleanupResult(
            candidate_count=len(managed),
            cutoff=cutoff.isoformat() if cutoff else None,
            deleted_count=len(deletable),
            dry_run=dry_run,
            refused_count=refused_count,
        )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--account-username",
        default=os.getenv("PROD_E2E_ACCOUNT_USERNAME"),
        help="Exact current-run account; omit to reap stale managed accounts",
    )
    parser.add_argument("--max-age-hours", type=int, default=DEFAULT_MAX_AGE_HOURS)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def _main() -> int:
    args = parse_args()
    try:
        result = await cleanup_e2e_accounts(
            account_username=args.account_username,
            max_age_hours=args.max_age_hours,
            dry_run=args.dry_run,
        )
        print(json.dumps(asdict(result), sort_keys=True))
        return 3 if result.refused_count else 0
    finally:
        await async_engine.dispose()


def main() -> int:
    """Run the disposable-account janitor."""
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
