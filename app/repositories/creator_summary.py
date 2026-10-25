"""Data access for the bounded personal creator summary aggregation (issue #2028).

Every SQLAlchemy query used by the creator summary endpoint lives here so the
router stays free of schema imports and ``execute`` calls (router-layering
contract). Every query is scoped to the authenticated user by an indexed
``threads.user_id`` predicate — never by a library-sized ``IN`` list — and none
of them fans out per creator or per issue: the whole batch request is served by
a fixed, bounded number of queries regardless of how many creator keys are
requested.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Numeric, case, cast, func, literal, or_, select, true
from sqlalchemy.dialects.postgresql import distinct_on, JSONB
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
    only and is never used as a grouping identity. ``issue_number`` is carried
    so bounded drilldown references (creator detail issue rows, comparison
    issue refs, and team-chemistry shared-issue refs) can label each issue
    without a further query.
    """

    thread_id: int
    thread_title: str
    issue_number: str = ""


@dataclass(frozen=True)
class CreatorSummaryInputs:
    """Plain, user-scoped inputs for the creator summary aggregation.

    Attributes:
        coverage_counts: Optional SQL aggregate counts for rated/covered,
            read-unrated/covered, and unread/covered issues across the entire library.
        owned_issues: Mapping of owned issue id to its ``read``/``unread`` status.
        owned_issue_series: Mapping of owned issue id to its stable local
            thread/series identity (issue #3088).
        issue_creator_credits: Mapping of owned issue id to its confirmed creator credits.
        issues_with_creator_metadata: Owned issues carrying at least one usable
            confirmed creator credit.
        effective_ratings: Mapping of owned issue id to its latest effective
            ``rate`` event rating (latest event by timestamp/id wins).
        effective_rating_timestamps: Mapping of owned issue id to its latest effective
            ``rate`` event timestamp (latest event by timestamp/id wins).
    """

    coverage_counts: tuple[int, int, int, int, int, int] | None = None
    owned_issues: dict[int, str] = field(default_factory=dict)
    owned_issue_series: dict[int, OwnedIssueSeries] = field(default_factory=dict)
    issue_creator_credits: dict[int, tuple[CreatorCredit, ...]] = field(default_factory=dict)
    issues_with_creator_metadata: frozenset[int] = field(default_factory=frozenset)
    effective_ratings: dict[int, float] = field(default_factory=dict)
    effective_rating_timestamps: dict[int, datetime] = field(default_factory=dict)


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


def extract_creator_credits(metadata: Mapping[str, object]) -> list[CreatorCredit]:
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

    The batch is served by exactly five queries no matter how many creator keys
    are requested — four aggregation reads plus the request's own
    authentication lookup:

    1. the authenticated user's owned issues and their thread ids;
    2. the user's threads: titles and manual creator credits, read once per
       thread instead of once per owned issue (issue #3387);
    3. the confirmed ``creator_credits`` key of ComicVine issue metadata for
       those issues, projected in SQL so the retained raw provider payload is
       never hydrated for a creator read (issue #3244);
    4. the latest effective ``rate`` event rating per owned issue;
    5. authentication lookup for the current user.

    Args:
        db: Async database session.
        user_id: Authenticated user whose library is aggregated.

    Returns:
        User-scoped :class:`CreatorSummaryInputs`.
    """
    # 1. Owned issues and thread ids.
    issue_result = await db.execute(
        select(Issue.id, Issue.status, Issue.thread_id, Issue.issue_number)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
    )
    owned_issues: dict[int, str] = {}
    thread_ids: set[int] = set()
    issue_thread_map: dict[int, int] = {}
    issue_number_map: dict[int, str] = {}
    for issue_id, status, thread_id, issue_number in issue_result.all():
        owned_issue_id = int(issue_id)
        owned_issues[owned_issue_id] = str(status)
        thread_id_int = int(thread_id)
        issue_thread_map[owned_issue_id] = thread_id_int
        issue_number_map[owned_issue_id] = str(issue_number)
        thread_ids.add(thread_id_int)

    # 2. Thread titles and manual creator credits, read once per thread.
    #
    # Projecting these columns off the issue join above repeated the stored
    # manual-credit document on every owned issue row, so a wide library
    # transferred and parsed the same JSON once per issue instead of once per
    # thread. Reading the user's threads directly keeps one row per thread and
    # keeps the statement user-scoped: filtering by ``id IN (...)`` would grow
    # one bind parameter per thread, which is exactly the wide-library shape
    # this read has to stay fast for. The set only guards the empty library,
    # which owns no thread to read.
    thread_manual_credits: dict[int, list[dict[str, object]]] = {}
    owned_issue_series: dict[int, OwnedIssueSeries] = {}
    if thread_ids:
        thread_result = await db.execute(
            select(Thread.id, Thread.title, Thread.manual_creator_credits).where(
                Thread.user_id == user_id
            )
        )
        thread_titles: dict[int, str] = {}
        for thread_id, title, manual_credits in thread_result.all():
            thread_id_int = int(thread_id)
            thread_titles[thread_id_int] = str(title)
            if manual_credits:
                thread_manual_credits[thread_id_int] = manual_credits
        for issue_id, thread_id in issue_thread_map.items():
            owned_issue_series[issue_id] = OwnedIssueSeries(
                thread_id=thread_id,
                thread_title=thread_titles.get(thread_id, ""),
                issue_number=issue_number_map.get(issue_id, ""),
            )

    # 3. Confirmed creator credits per owned issue (ComicVine).
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

    # 4. Manual thread-level creator credits for issues without ComicVine metadata.
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

    # 5. Latest effective rating and timestamp per owned issue (latest event wins).
    # PostgreSQL ``DISTINCT ON`` collapses the user's rate events to one row per
    # owned issue inside the database. ``distinct(Event.issue_id)`` would render
    # the same SQL but is deprecated on SQLAlchemy 2.1 and emits
    # ``SADeprecationWarning``; ``postgresql.distinct_on`` applied as a
    # statement extension is the supported spelling.
    rate_result = await db.execute(
        select(Event.issue_id, Event.rating, Event.timestamp)
        .join(Issue, Issue.id == Event.issue_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
        .where(Event.type == "rate")
        .where(Event.issue_id.is_not(None))
        .where(Event.rating.is_not(None))
        .order_by(Event.issue_id, Event.timestamp.desc(), Event.id.desc())
        .ext(distinct_on(Event.issue_id))
    )
    effective_ratings: dict[int, float] = {}
    effective_rating_timestamps: dict[int, datetime] = {}
    for rated_issue_id, rating, timestamp in rate_result.all():
        if rated_issue_id is None or rating is None:
            continue
        normalized_issue_id = int(rated_issue_id)
        effective_ratings[normalized_issue_id] = float(rating)
        if timestamp is not None:
            effective_rating_timestamps[normalized_issue_id] = timestamp

    return CreatorSummaryInputs(
        owned_issues=owned_issues,
        owned_issue_series=owned_issue_series,
        issue_creator_credits=issue_creator_credits,
        issues_with_creator_metadata=frozenset(issues_with_creator_metadata),
        effective_ratings=effective_ratings,
        effective_rating_timestamps=effective_rating_timestamps,
    )


async def load_creator_summary_inputs_for_creators(
    db: AsyncSession,
    user_id: int,
    requested_creator_ids: set[int],
) -> CreatorSummaryInputs:
    """Load user-scoped inputs for creator summary, filtered to requested creator IDs.

    This variant uses SQLAlchemy Core / PostgreSQL set-based reads to project only
    the requested creator credits, avoiding full-library hydration in Python.
    The query count stays constant regardless of library size; fetched rows scale
    with the number of requested creators and their attributed issues.

    Args:
        db: Async database session.
        user_id: Authenticated user whose library is aggregated.
        requested_creator_ids: Set of external person IDs to include.

    Returns:
        User-scoped :class:`CreatorSummaryInputs` containing only data for the
        requested creators (plus global coverage totals).
    """
    # Manual names use the existing stable hash in Python. Read each stored
    # thread credit list once, never once per issue, then bind matching threads.
    manual_result = await db.execute(
        select(Thread.id, Thread.manual_creator_credits)
        .where(Thread.user_id == user_id)
        .where(Thread.manual_creator_credits.is_not(None))
    )
    manual_by_thread = {
        int(thread_id): tuple(extract_manual_creator_credits(raw or []))
        for thread_id, raw in manual_result.all()
    }
    covered_manual_threads = [tid for tid, credits in manual_by_thread.items() if credits]
    requested_manual_threads = [
        tid
        for tid, credits in manual_by_thread.items()
        if any(c.external_id in requested_creator_ids for c in credits)
    ]
    owned = (
        select(Issue.id, Issue.status, Issue.thread_id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
        .cte("owned_creator_issues")
        .prefix_with("NOT MATERIALIZED")
    )
    arrays = (
        select(
            owned.c.id.label("issue_id"),
            cast(ExternalIdentity.metadata_json[CREATOR_CREDITS_KEY], JSONB).label("credits"),
        )
        .select_from(owned)
        .join(IssueExternalIdentityMapping, IssueExternalIdentityMapping.issue_id == owned.c.id)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(IssueExternalIdentityMapping.status == "confirmed")
        .where(ExternalIdentity.provider == COMICVINE_PROVIDER)
        .cte("creator_credit_arrays")
        .prefix_with("MATERIALIZED")
    )
    raw_credits = arrays.c.credits
    elements = (
        func.jsonb_array_elements(
            case(
                (func.jsonb_typeof(raw_credits) == "array", raw_credits),
                else_=cast(literal([], type_=JSONB), JSONB),
            )
        )
        .table_valued("value")
        .lateral()
    )
    value = cast(elements.c.value, JSONB)
    creator_id_text = value["id"].astext
    # CASE protects the numeric cast even when the planner reorders predicates.
    creator_id = case(
        (creator_id_text.op("~")(r"^-?[0-9]+$"), cast(creator_id_text, Numeric)),
        else_=None,
    )
    valid_credits = (
        select(arrays.c.issue_id, value.label("credit"), creator_id.label("creator_id"))
        .select_from(arrays)
        .join(elements, true())
        .where(creator_id.is_not(None))
        .where(func.jsonb_typeof(value["name"]) == "string")
        .where(func.btrim(value["name"].astext) != "")
        .cte("usable_creator_credits")
    )
    confirmed = select(valid_credits.c.issue_id).distinct().cte("confirmed_creator_issues")
    latest = (
        select(Event.issue_id, Event.rating)
        .join(owned, owned.c.id == Event.issue_id)
        .where(Event.type == "rate", Event.rating.is_not(None))
        .order_by(Event.issue_id, Event.timestamp.desc(), Event.id.desc())
        .ext(distinct_on(Event.issue_id))
        .cte("latest_creator_ratings")
        .prefix_with("NOT MATERIALIZED")
    )
    covered = or_(confirmed.c.issue_id.is_not(None), owned.c.thread_id.in_(covered_manual_threads))
    rated = latest.c.rating.is_not(None)
    read_unrated = (owned.c.status == "read") & ~rated
    unread = owned.c.status == "unread"
    coverage = (
        select(
            *[
                func.count().filter(predicate).label(f"count_{index}")
                for index, predicate in enumerate(
                    (
                        rated,
                        rated & covered,
                        read_unrated,
                        read_unrated & covered,
                        unread,
                        unread & covered,
                    )
                )
            ]
        )
        .select_from(owned)
        .outerjoin(confirmed, confirmed.c.issue_id == owned.c.id)
        .outerjoin(latest, latest.c.issue_id == owned.c.id)
        .cte("creator_coverage")
    )
    requested = (
        select(valid_credits.c.issue_id, valid_credits.c.credit)
        .where(valid_credits.c.creator_id.in_(requested_creator_ids))
        .cte("requested_creator_credits")
    )
    matching = (
        select(owned.c.id, owned.c.status, owned.c.thread_id, requested.c.credit, latest.c.rating)
        .select_from(owned)
        .outerjoin(confirmed, confirmed.c.issue_id == owned.c.id)
        .outerjoin(requested, requested.c.issue_id == owned.c.id)
        .outerjoin(latest, latest.c.issue_id == owned.c.id)
        .where(
            or_(
                requested.c.issue_id.is_not(None),
                confirmed.c.issue_id.is_(None) & owned.c.thread_id.in_(requested_manual_threads),
            )
        )
        .cte("matching_creator_issues")
    )
    # Share extracted credit arrays between attribution and coverage. Reading
    # the large source JSON twice was slower than the old Python aggregation.
    rows = await db.execute(
        select(matching, coverage)
        .select_from(coverage)
        .outerjoin(matching, true())
        .order_by(matching.c.id)
    )
    coverage_counts = None
    statuses: dict[int, str] = {}
    ratings: dict[int, float] = {}
    credits_by_issue: dict[int, dict[tuple[int, tuple[str, ...]], CreatorCredit]] = {}
    for row in rows.all():
        coverage_counts = (
            int(row[5]),
            int(row[6]),
            int(row[7]),
            int(row[8]),
            int(row[9]),
            int(row[10]),
        )
        if row[0] is None:
            continue
        issue_id = int(row[0])
        status = str(row[1])
        thread_id = int(row[2])
        raw_credit = row[3]
        rating = row[4]
        statuses[issue_id] = status
        if rating is not None:
            ratings[issue_id] = float(rating)
        credits = (
            extract_creator_credit_list([raw_credit])
            if raw_credit is not None
            else [
                c
                for c in manual_by_thread.get(thread_id, ())
                if c.external_id in requested_creator_ids
            ]
        )
        by_key = credits_by_issue.setdefault(issue_id, {})
        for credit in credits:
            by_key.setdefault((credit.external_id, credit.roles), credit)
    return CreatorSummaryInputs(
        coverage_counts=coverage_counts,
        owned_issues=statuses,
        issue_creator_credits={
            iid: tuple(sorted(cs.values(), key=lambda credit: (credit.external_id, credit.roles)))
            for iid, cs in credits_by_issue.items()
        },
        effective_ratings=ratings,
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
    "load_creator_summary_inputs_for_creators",
    "manual_creator_id",
]
