"""Data access for the bounded personal creator summary aggregation (issue #2028).

Every SQLAlchemy query used by the creator summary endpoint lives here so the
router stays free of schema imports and ``execute`` calls (router-layering
contract). All queries are user-scoped joins with no per-creator or per-issue
fan-out: the whole batch request is served by a fixed, bounded number of
queries regardless of how many creator keys are requested.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread

COMICVINE_PROVIDER = "comicvine"

#: Key inside normalized issue metadata that holds provider creator credits.
#: Named so the SQL projection and the Python extractor cannot drift apart.
CREATOR_CREDITS_KEY = "creator_credits"


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
class OwnedIssueSeries:
    """Stable local series/run identity attached to one owned issue.

    ComicPile's series identity is the thread: one thread is one series or one
    creator run in the reader's own library. The title is carried for display
    only and is never used as a grouping identity.

    Attributes:
        thread_id: Local ComicPile thread (series/run) id owning the issue.
        thread_title: Current local thread title, for display only.
    """

    thread_id: int
    thread_title: str


@dataclass(frozen=True)
class CreatorSummaryInputs:
    """Plain, user-scoped inputs for the creator summary aggregation.

    Attributes:
        owned_issues: Mapping of owned issue id to its ``read``/``unread`` status.
        owned_issue_series: Mapping of owned issue id to its stable local
            thread/series identity (issue #3088).
        issue_creator_credits: Mapping of owned issue id to its confirmed creator credits.
        issues_with_creator_metadata: Owned issues carrying at least one usable
            confirmed creator credit.
        effective_ratings: Mapping of owned issue id to its latest effective
            ``rate`` event rating (latest event by timestamp/id wins).
    """

    owned_issues: dict[int, str] = field(default_factory=dict)
    owned_issue_series: dict[int, OwnedIssueSeries] = field(default_factory=dict)
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


def extract_creator_credit_list(raw: object) -> list[CreatorCredit]:
    """Extract deduplicated creator credits from one provider credit list.

    This is the single-credit-list entry point shared by the full-metadata and
    projected-column readers. ``load_creator_summary_inputs`` only needs this
    list, so the creator read projects it out of ``metadata_json`` in SQL and
    never hydrates the whole normalized provider payload (issue #3244).

    Args:
        raw: Raw ``creator_credits`` value read from normalized issue metadata.

    Returns:
        One :class:`CreatorCredit` per distinct (creator id, role set).
    """
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
    return extract_creator_credit_list(metadata.get("creator_credits"))


#: Reserved identifier band for manually entered creators. Provider person ids
#: live far below this floor, so a manual credit can share the aggregation key
#: space with ComicVine credits without ever colliding with a provider id.
MANUAL_CREATOR_ID_BASE = 1_000_000_000

#: Friendly manual-entry role labels mapped onto the canonical lowercase
#: provider role vocabulary so headline classification sees one dialect.
_MANUAL_ROLE_ALIASES: dict[str, str] = {
    "cover artist": "cover",
    "penciller": "penciler",
}


def manual_creator_id(name: str) -> int:
    """Derive the stable synthetic person id for a manually entered creator.

    ``hash()`` is randomized per interpreter, so it must never key creator
    identity: the same name would otherwise resolve to a different canonical
    creator key after a process restart and every saved creator link would
    break. A SHA-256 digest keeps the id stable across processes and maps it
    into the reserved manual band.

    Args:
        name: Normalized (whitespace-collapsed) creator display name.

    Returns:
        A deterministic id in
        ``[MANUAL_CREATOR_ID_BASE, 2 * MANUAL_CREATOR_ID_BASE)``.
    """
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return MANUAL_CREATOR_ID_BASE + int(digest, 16) % MANUAL_CREATOR_ID_BASE


def _split_roles(item: dict[str, object]) -> list[str]:
    """Return the raw role strings stored on one manual credit.

    Args:
        item: One stored manual creator credit dictionary.

    Returns:
        Candidate role strings before normalization.
    """
    role_value = item.get("roles")
    if isinstance(role_value, list):
        return [part for part in role_value if isinstance(part, str)]
    if isinstance(role_value, str):
        return role_value.split(",")
    return []


def _normalize_manual_role(role: str) -> str | None:
    """Normalize one manual role token to the canonical provider vocabulary.

    Args:
        role: Raw role token supplied by the client.

    Returns:
        The trimmed, lowercased, alias-resolved role, or ``None`` when the
        token carries no role text.
    """
    normalized = " ".join(role.split()).lower()
    if not normalized:
        return None
    return _MANUAL_ROLE_ALIASES.get(normalized, normalized)


def extract_manual_creator_credits(manual_credits: list[dict[str, object]]) -> list[CreatorCredit]:
    """Extract deduplicated creator credits from manual thread metadata.

    Manual credits carry no provider id, so each distinct normalized name is
    mapped into :data:`MANUAL_CREATOR_ID_BASE`, a reserved band no provider
    person id reaches. Role tokens are normalized to the same lowercase
    vocabulary ComicVine credits use so headline classification
    (``HEADLINE_ROLES``) treats manual and provider credits identically.

    Args:
        manual_credits: List of manual creator credit dicts with 'name' and 'roles'.

    Returns:
        One :class:`CreatorCredit` per distinct (synthetic id, role set).
    """
    credits: list[CreatorCredit] = []
    seen: set[tuple[int, tuple[str, ...]]] = set()
    for item in manual_credits:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        normalized_name = " ".join(name.split())
        roles = tuple(
            sorted(
                {
                    role
                    for role in (_normalize_manual_role(part) for part in _split_roles(item))
                    if role is not None
                }
            )
        )
        synthetic_id = manual_creator_id(normalized_name)
        dedupe = (synthetic_id, roles)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        credits.append(
            CreatorCredit(
                external_id=synthetic_id,
                roles=roles,
                display_name=normalized_name,
            )
        )
    return credits


async def load_creator_summary_inputs(
    db: AsyncSession,
    user_id: int,
) -> CreatorSummaryInputs:
    """Load every user-scoped input needed for one bounded batch aggregation.

    The batch is served by exactly four queries no matter how many creator
    keys are requested:

    1. the authenticated user's owned issues, their read/unread status, and
       their stable local thread/series identity;
    2. the confirmed ``creator_credits`` key of ComicVine issue metadata for
       those issues, projected in SQL so the retained raw provider payload is
       never hydrated for a creator read (issue #3244);
    3. manual thread-level creator credits for threads without issue metadata;
    4. the latest effective ``rate`` event rating per owned issue.

    Args:
        db: Async database session.
        user_id: Authenticated user whose library is aggregated.

    Returns:
        User-scoped :class:`CreatorSummaryInputs`.
    """
    # 1. Owned issues, statuses, and stable local series identity.
    issue_result = await db.execute(
        select(Issue.id, Issue.status, Issue.thread_id, Thread.title, Thread.manual_creator_credits)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
    )
    owned_issues: dict[int, str] = {}
    owned_issue_series: dict[int, OwnedIssueSeries] = {}
    thread_manual_credits: dict[int, list[dict[str, object]]] = {}
    for issue_id, status, thread_id, thread_title, manual_credits in issue_result.all():
        owned_issue_id = int(issue_id)
        owned_issues[owned_issue_id] = str(status)
        owned_issue_series[owned_issue_id] = OwnedIssueSeries(
            thread_id=int(thread_id),
            thread_title=str(thread_title),
        )
        thread_id_int = int(thread_id)
        if manual_credits and thread_id_int not in thread_manual_credits:
            thread_manual_credits[thread_id_int] = manual_credits

    # 2. Confirmed creator credits per owned issue (ComicVine).
    # Only ``metadata_json->'creator_credits'`` is projected. Normalized issue
    # metadata also retains the complete raw ComicVine provider payload, and
    # hydrating that payload for every owned issue on every creator read is what
    # pushed this route into multi-second responses (issue #3244).
    metadata_result = await db.execute(
        select(Issue.id, ExternalIdentity.metadata_json[CREATOR_CREDITS_KEY])
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
    for issue_id, raw_credits in metadata_result.all():
        credits = extract_creator_credit_list(raw_credits)
        owned_issue_id = int(issue_id)
        if credits:
            issues_with_creator_metadata.add(owned_issue_id)
        by_key = per_issue_credits.setdefault(owned_issue_id, {})
        for credit in credits:
            by_key.setdefault((credit.external_id, credit.roles), credit)

    # 3. Manual thread-level creator credits for issues without ComicVine metadata.
    for issue_id, series in owned_issue_series.items():
        if issue_id in issues_with_creator_metadata:
            continue
        manual_credits = thread_manual_credits.get(series.thread_id, [])
        if manual_credits:
            credits = extract_manual_creator_credits(manual_credits)
            if credits:
                issues_with_creator_metadata.add(issue_id)
                by_key = per_issue_credits.setdefault(issue_id, {})
                for credit in credits:
                    by_key.setdefault((credit.external_id, credit.roles), credit)

    issue_creator_credits: dict[int, tuple[CreatorCredit, ...]] = {
        issue_id: tuple(
            sorted(by_key.values(), key=lambda credit: (credit.external_id, credit.roles))
        )
        for issue_id, by_key in per_issue_credits.items()
    }

    # 4. Latest effective rating per owned issue (latest event wins).
    # PostgreSQL ``DISTINCT ON`` collapses the user's rate events to one row per
    # owned issue inside the database. ``distinct(Event.issue_id)`` would render
    # the same SQL but is deprecated on SQLAlchemy 2.1 and emits
    # ``SADeprecationWarning``; ``postgresql.distinct_on`` applied as a
    # statement extension is the supported spelling.
    rate_result = await db.execute(
        select(Event.issue_id, Event.rating)
        .join(Issue, Issue.id == Event.issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
        .where(Event.type == "rate")
        .where(Event.issue_id.is_not(None))
        .where(Event.rating.is_not(None))
        .order_by(Event.issue_id, Event.timestamp.desc(), Event.id.desc())
        .distinct()
        .ext(distinct_on(Event.issue_id))
    )
    effective_ratings: dict[int, float] = {
        int(issue_id): float(rating) for issue_id, rating in rate_result.all() if issue_id is not None
    }

    return CreatorSummaryInputs(
        owned_issues=owned_issues,
        owned_issue_series=owned_issue_series,
        issue_creator_credits=issue_creator_credits,
        issues_with_creator_metadata=frozenset(issues_with_creator_metadata),
        effective_ratings=effective_ratings,
    )


__all__ = [
    "COMICVINE_PROVIDER",
    "CREATOR_CREDITS_KEY",
    "MANUAL_CREATOR_ID_BASE",
    "CreatorCredit",
    "CreatorSummaryInputs",
    "OwnedIssueSeries",
    "extract_creator_credit_list",
    "extract_creator_credits",
    "extract_manual_creator_credits",
    "load_creator_summary_inputs",
    "manual_creator_id",
]
