"""Data access for the bounded personal creator summary aggregation (issue #2028).

Every SQLAlchemy query used by the creator summary endpoint lives here so the
router stays free of schema imports and ``execute`` calls (router-layering
contract). All queries are user-scoped joins with no per-creator or per-issue
fan-out: the whole batch request is served by a fixed, bounded number of
queries regardless of how many creator keys are requested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread

COMICVINE_PROVIDER = "comicvine"


@dataclass(frozen=True)
class CreatorCredit:
    """One deduplicated creator credit extracted from confirmed issue metadata.

    Attributes:
        external_id: Stable external provider person identifier.
        roles: Normalized role set on the credit (empty when the credit had no role).
        display_name: Provider display name attached to the credit.
    """

    external_id: int
    roles: tuple[str, ...] = field(default_factory=tuple)
    display_name: str = ""


@dataclass(frozen=True)
class CreatorSummaryInputs:
    """Plain, user-scoped inputs for the creator summary aggregation.

    Attributes:
        owned_issues: Mapping of owned issue id to its ``read``/``unread`` status.
        issue_creator_credits: Mapping of owned issue id to its confirmed creator credits.
        issues_with_creator_metadata: Owned issues carrying at least one usable
            confirmed creator credit.
        effective_ratings: Mapping of owned issue id to its latest effective
            ``rate`` event rating (latest event by timestamp/id wins).
    """

    owned_issues: dict[int, str] = field(default_factory=dict)
    issue_creator_credits: dict[int, tuple[CreatorCredit, ...]] = field(default_factory=dict)
    issues_with_creator_metadata: frozenset[int] = field(default_factory=frozenset)
    effective_ratings: dict[int, float] = field(default_factory=dict)


def _coerce_creator_id(value: object) -> int | None:
    """Coerce a provider person id to an int when it is numeric.

    Args:
        value: Raw provider person identifier.

    Returns:
        The integer identifier, or ``None`` when not numeric.
    """
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def extract_creator_credits(metadata: dict[str, Any]) -> list[CreatorCredit]:
    """Extract deduplicated creator credits from confirmed issue metadata.

    Credits must carry a stable external person id and a display name to be
    analytics-addressable. A credit with no usable id is never guessed into a
    key (issue #2036). Provider role strings may be comma-joined; each distinct
    role is preserved separately.

    Args:
        metadata: Normalized ComicVine issue ``metadata_json``.

    Returns:
        One :class:`CreatorCredit` per distinct (creator id, role set).
    """
    raw = metadata.get("creator_credits")
    if not isinstance(raw, list):
        return []
    credits: list[CreatorCredit] = []
    seen: set[tuple[int, tuple[str, ...]]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        creator_id = _coerce_creator_id(item.get("id"))
        name = item.get("name")
        if creator_id is None or not isinstance(name, str) or not name.strip():
            continue
        role_value = item.get("role")
        roles: tuple[str, ...] = ()
        if role_value is not None:
            parsed = {part.strip() for part in str(role_value).split(",") if part.strip()}
            roles = tuple(sorted(parsed))
        dedupe = (creator_id, roles)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        credits.append(
            CreatorCredit(
                external_id=creator_id,
                roles=roles,
                display_name=name.strip(),
            )
        )
    return credits


async def load_creator_summary_inputs(
    db: AsyncSession,
    user_id: int,
) -> CreatorSummaryInputs:
    """Load every user-scoped input needed for one bounded batch aggregation.

    The batch is served by exactly three queries no matter how many creator
    keys are requested:

    1. the authenticated user's owned issues and their read/unread status;
    2. confirmed ComicVine issue metadata for those issues (creator credits);
    3. the latest effective ``rate`` event rating per owned issue.

    Args:
        db: Async database session.
        user_id: Authenticated user whose library is aggregated.

    Returns:
        User-scoped :class:`CreatorSummaryInputs`.
    """
    # 1. Owned issues and statuses.
    issue_result = await db.execute(
        select(Issue.id, Issue.status)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
    )
    owned_issues: dict[int, str] = {
        int(issue_id): str(status) for issue_id, status in issue_result.all()
    }

    # 2. Confirmed creator credits per owned issue.
    metadata_result = await db.execute(
        select(Issue.id, ExternalIdentity.metadata_json)
        .join(Thread, Thread.id == Issue.thread_id)
        .join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.issue_id == Issue.id,
        )
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(Thread.user_id == user_id)
        .where(IssueExternalIdentityMapping.status == "confirmed")
        .where(ExternalIdentity.provider == COMICVINE_PROVIDER)
    )
    per_issue_credits: dict[int, dict[tuple[int, tuple[str, ...]], CreatorCredit]] = {}
    issues_with_creator_metadata: set[int] = set()
    for issue_id, metadata in metadata_result.all():
        if not isinstance(metadata, dict):
            continue
        credits = extract_creator_credits(metadata)
        owned_issue_id = int(issue_id)
        if credits:
            issues_with_creator_metadata.add(owned_issue_id)
        by_key = per_issue_credits.setdefault(owned_issue_id, {})
        for credit in credits:
            by_key.setdefault((credit.external_id, credit.roles), credit)
    issue_creator_credits: dict[int, tuple[CreatorCredit, ...]] = {
        issue_id: tuple(
            sorted(by_key.values(), key=lambda credit: (credit.external_id, credit.roles))
        )
        for issue_id, by_key in per_issue_credits.items()
    }

    # 3. Latest effective rating per owned issue (latest event wins).
    rate_result = await db.execute(
        select(Event.issue_id, Event.rating)
        .join(Issue, Issue.id == Event.issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
        .where(Event.type == "rate")
        .where(Event.issue_id.is_not(None))
        .where(Event.rating.is_not(None))
        .order_by(Event.issue_id, Event.timestamp.desc(), Event.id.desc())
    )
    effective_ratings: dict[int, float] = {}
    for issue_id, rating in rate_result.all():
        if issue_id is not None and int(issue_id) not in effective_ratings:
            effective_ratings[int(issue_id)] = float(rating)

    return CreatorSummaryInputs(
        owned_issues=owned_issues,
        issue_creator_credits=issue_creator_credits,
        issues_with_creator_metadata=frozenset(issues_with_creator_metadata),
        effective_ratings=effective_ratings,
    )


__all__ = [
    "COMICVINE_PROVIDER",
    "CreatorCredit",
    "CreatorSummaryInputs",
    "extract_creator_credits",
    "load_creator_summary_inputs",
]