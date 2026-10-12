"""Audit and safe repair of read-without-rating issues (issue #3175).

Proves the closure-critical contract: the audit counts the exact
read-without-rating population shared with the creator comparison, every
row carries an evidenced classification, only safely matchable historical
ratings become effective ``rate`` events, ambiguous rows stay unresolved,
reruns create no duplicates, and the read-unrated drilldown surfaces the
cause per row.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.repositories.read_without_rating_audit import ThreadHistoricalRating
from app.services.creator_metric_drilldown import get_creator_metric_drilldown
from app.services.read_without_rating_audit import (
    CAUSE_AMBIGUOUS_THREAD_RATING,
    CAUSE_EDITION_CONFLICT,
    CAUSE_MISSING_RATE_EVENT,
    CAUSE_NO_SOURCE_RATING,
    CAUSE_UNRESOLVED_MAPPING,
    audit_read_without_rating,
    classify_missing_rating,
    repair_safe_missing_ratings,
)

D1 = datetime(2026, 3, 1, tzinfo=UTC)
D2 = datetime(2026, 3, 2, tzinfo=UTC)

_identity_serial = 0


async def _make_thread(
    db: AsyncSession,
    user: User,
    *,
    title: str,
    issue_count: int,
    queue_position: int,
    read_through: int = 0,
    first_number: int = 1,
) -> tuple[Thread, list[Issue]]:
    """Create an owned thread with contiguous issues.

    ``first_number`` shifts the display issue numbers so tests with several
    threads avoid accidental cross-thread duplicates (which the audit
    classifies as edition conflicts).
    """
    thread = Thread(
        user_id=user.id,
        title=title,
        format="Comic",
        issues_remaining=issue_count - read_through,
        total_issues=issue_count,
        queue_position=queue_position,
        status="active",
    )
    db.add(thread)
    await db.flush()
    issues = []
    for position in range(1, issue_count + 1):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(first_number + position - 1),
            position=position,
            status="read" if position <= read_through else "unread",
        )
        db.add(issue)
        issues.append(issue)
    await db.flush()
    return thread, issues


async def _confirm_identity(
    db: AsyncSession,
    issue: Issue,
    *,
    creators: list[dict[str, object]] | None = None,
) -> None:
    """Create a confirmed external issue identity mapping."""
    global _identity_serial
    _identity_serial += 1
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=f"audit-{_identity_serial}",
        metadata_json={"creator_credits": creators or []},
    )
    db.add(identity)
    await db.flush()
    db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="confirmed",
            confidence=1.0,
        )
    )
    await db.flush()


async def _confirm_shared_identity(
    db: AsyncSession,
    first: Issue,
    second: Issue,
) -> None:
    """Confirm two local issues against one shared external issue identity."""
    global _identity_serial
    _identity_serial += 1
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=f"shared-{_identity_serial}",
        metadata_json={"creator_credits": []},
    )
    db.add(identity)
    await db.flush()
    for issue in (first, second):
        db.add(
            IssueExternalIdentityMapping(
                issue_id=issue.id,
                external_identity_id=identity.id,
                status="confirmed",
                confidence=1.0,
            )
        )
    await db.flush()


async def _candidate_mapping(db: AsyncSession, issue: Issue) -> None:
    """Create a candidate (non-confirmed) identity mapping for an issue."""
    global _identity_serial
    _identity_serial += 1
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=f"audit-{_identity_serial}",
        metadata_json={"creator_credits": []},
    )
    db.add(identity)
    await db.flush()
    db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="candidate",
            confidence=0.4,
        )
    )
    await db.flush()


async def _rate(
    db: AsyncSession,
    issue: Issue,
    *,
    rating: float,
    timestamp: datetime,
) -> Event:
    """Create one issue-linked rate event for an issue."""
    event = Event(
        type="rate",
        thread_id=issue.thread_id,
        issue_id=issue.id,
        issue_number=issue.issue_number,
        rating=rating,
        timestamp=timestamp,
    )
    db.add(event)
    await db.flush()
    return event


async def _thread_rate(
    db: AsyncSession,
    thread: Thread,
    *,
    rating: float,
    timestamp: datetime,
) -> Event:
    """Create one thread-level historical rate event (no issue linkage)."""
    event = Event(
        type="rate",
        thread_id=thread.id,
        issue_id=None,
        rating=rating,
        timestamp=timestamp,
    )
    db.add(event)
    await db.flush()
    return event


async def _issue_rate_events(db: AsyncSession, issue_id: int) -> list[Event]:
    """Return all rate events targeting one issue, oldest first."""
    result = await db.execute(
        select(Event)
        .where(Event.type == "rate")
        .where(Event.issue_id == issue_id)
        .order_by(Event.timestamp.asc(), Event.id.asc())
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_safe_match_repaired_and_totals_reconcile(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A safely matchable historical rating becomes one effective event."""
    thread_a, issues_a = await _make_thread(
        async_db, default_user, title="Team Book", issue_count=1, queue_position=1,
        read_through=1,
    )
    await _confirm_identity(
        async_db,
        issues_a[0],
        creators=[{"id": 1, "name": "Chris Claremont", "role": "writer"}],
    )
    await _thread_rate(async_db, thread_a, rating=4.5, timestamp=D1)
    _thread_b, issues_b = await _make_thread(
        async_db, default_user, title="Solo Book", issue_count=1, queue_position=2,
        read_through=1, first_number=2,
    )
    await _confirm_identity(async_db, issues_b[0])
    await _rate(async_db, issues_b[0], rating=3.0, timestamp=D2)

    pre = await audit_read_without_rating(async_db, default_user.id)
    assert pre.total == 1
    assert pre.by_cause == {CAUSE_MISSING_RATE_EVENT: 1}
    assert pre.effective_rated_issues == 1
    assert pre.issues[0].issue_id == issues_a[0].id
    assert pre.issues[0].cause.repair_safe is True
    assert pre.issues[0].cause.source_rating == 4.5

    report = await repair_safe_missing_ratings(async_db, default_user.id)
    assert report.effective_before == 1
    assert report.repaired == 1
    assert report.repaired_issue_ids == [issues_a[0].id]
    assert report.effective_after == 2
    assert report.skipped_by_cause == {}

    events = await _issue_rate_events(async_db, issues_a[0].id)
    assert len(events) == 1
    assert events[0].rating == pytest.approx(4.5)
    assert events[0].thread_id == thread_a.id
    assert events[0].issue_number == "1"
    assert events[0].timestamp == D1

    post = await audit_read_without_rating(async_db, default_user.id)
    assert post.total == 0
    assert post.by_cause == {}
    assert post.effective_rated_issues == 2


@pytest.mark.asyncio
async def test_no_source_rating_left_unrated(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A confirmed read issue with no rating signal stays unrated."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Team Book", issue_count=1, queue_position=1,
        read_through=1,
    )
    await _confirm_identity(async_db, issues[0])

    audit = await audit_read_without_rating(async_db, default_user.id)
    assert audit.total == 1
    assert audit.by_cause == {CAUSE_NO_SOURCE_RATING: 1}
    assert audit.issues[0].cause.repair_safe is False
    assert audit.issues[0].cause.missing_evidence == ""

    report = await repair_safe_missing_ratings(async_db, default_user.id)
    assert report.repaired == 0
    assert report.effective_before == 0
    assert report.effective_after == 0
    assert report.skipped_by_cause == {CAUSE_NO_SOURCE_RATING: 1}
    assert await _issue_rate_events(async_db, issues[0].id) == []


@pytest.mark.asyncio
async def test_unresolved_mapping_names_missing_evidence(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Issues without a confirmed mapping name the missing evidence."""
    _plain_thread, plain_issues = await _make_thread(
        async_db, default_user, title="Plain Book", issue_count=1, queue_position=1,
        read_through=1,
    )
    _candidate_thread, candidate_issues = await _make_thread(
        async_db, default_user, title="Candidate Book", issue_count=1, queue_position=2,
        read_through=1, first_number=2,
    )
    await _candidate_mapping(async_db, candidate_issues[0])

    audit = await audit_read_without_rating(async_db, default_user.id)
    assert audit.total == 2
    assert audit.by_cause == {CAUSE_UNRESOLVED_MAPPING: 2}
    for row in audit.issues:
        assert row.cause.repair_safe is False
        assert (
            row.cause.missing_evidence == "confirmed external issue identity mapping"
        )
    by_id = {row.issue_id: row for row in audit.issues}
    assert by_id[plain_issues[0].id].cause.detail["mapping_statuses"] == []
    assert by_id[candidate_issues[0].id].cause.detail["mapping_statuses"] == [
        "candidate"
    ]

    report = await repair_safe_missing_ratings(async_db, default_user.id)
    assert report.repaired == 0
    assert report.skipped_by_cause == {CAUSE_UNRESOLVED_MAPPING: 2}


@pytest.mark.asyncio
async def test_ambiguous_thread_rating_multiple_issues(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """One thread-level rating shared by several issues is never guessed."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Team Book", issue_count=2, queue_position=1,
        read_through=2,
    )
    for issue in issues:
        await _confirm_identity(async_db, issue)
    await _thread_rate(async_db, thread, rating=4.0, timestamp=D1)

    audit = await audit_read_without_rating(async_db, default_user.id)
    assert audit.total == 2
    assert audit.by_cause == {CAUSE_AMBIGUOUS_THREAD_RATING: 2}
    assert audit.by_thread[thread.id].total == 2
    assert audit.by_thread[thread.id].by_cause == {CAUSE_AMBIGUOUS_THREAD_RATING: 2}
    for row in audit.issues:
        assert row.cause.repair_safe is False
        assert row.cause.detail["unrated_read_in_thread"] == 2

    report = await repair_safe_missing_ratings(async_db, default_user.id)
    assert report.repaired == 0
    assert report.effective_after == 0
    for issue in issues:
        assert await _issue_rate_events(async_db, issue.id) == []


@pytest.mark.asyncio
async def test_ambiguous_thread_rating_conflicting_values(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Disagreeing thread-level ratings are never merged into a guess."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Solo Book", issue_count=1, queue_position=1,
        read_through=1,
    )
    await _confirm_identity(async_db, issues[0])
    await _thread_rate(async_db, thread, rating=4.0, timestamp=D1)
    await _thread_rate(async_db, thread, rating=3.0, timestamp=D2)

    audit = await audit_read_without_rating(async_db, default_user.id)
    assert audit.total == 1
    assert audit.by_cause == {CAUSE_AMBIGUOUS_THREAD_RATING: 1}
    assert audit.issues[0].cause.detail["rating_values"] == [3.0, 4.0]

    report = await repair_safe_missing_ratings(async_db, default_user.id)
    assert report.repaired == 0
    assert await _issue_rate_events(async_db, issues[0].id) == []


@pytest.mark.asyncio
async def test_edition_conflict_blocks_repair_despite_rating(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Two copies confirmed to one external identity block attribution."""
    thread_a, issues_a = await _make_thread(
        async_db, default_user, title="Team Book", issue_count=1, queue_position=1,
        read_through=1,
    )
    _thread_b, issues_b = await _make_thread(
        async_db, default_user, title="Team Book Reprint", issue_count=1,
        queue_position=2, read_through=1,
    )
    # Both local issues resolve to the same provider issue: a genuine
    # edition/duplicate conflict.
    await _confirm_shared_identity(async_db, issues_a[0], issues_b[0])
    await _thread_rate(async_db, thread_a, rating=4.5, timestamp=D1)

    audit = await audit_read_without_rating(async_db, default_user.id)
    assert audit.total == 2
    assert audit.by_cause == {CAUSE_EDITION_CONFLICT: 2}
    by_id = {row.issue_id: row for row in audit.issues}
    conflict = by_id[issues_a[0].id]
    assert conflict.cause.cause == CAUSE_EDITION_CONFLICT
    assert conflict.cause.repair_safe is False
    assert conflict.cause.detail["duplicate_issue_ids"] == [issues_b[0].id]
    mirror = by_id[issues_b[0].id]
    assert mirror.cause.cause == CAUSE_EDITION_CONFLICT
    assert mirror.cause.detail["duplicate_issue_ids"] == [issues_a[0].id]

    report = await repair_safe_missing_ratings(async_db, default_user.id)
    assert report.repaired == 0
    assert await _issue_rate_events(async_db, issues_a[0].id) == []


@pytest.mark.asyncio
async def test_shared_issue_number_across_threads_is_not_a_conflict(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Two unrelated series both numbered 1 are not an edition conflict.

    Every ComicPile series restarts at issue 1, so number collisions across
    threads are the norm. Treating them as duplicates would classify the whole
    library as conflicted and suppress every repair.
    """
    thread_a, issues_a = await _make_thread(
        async_db, default_user, title="Alpha", issue_count=1, queue_position=1,
        read_through=1,
    )
    _thread_b, issues_b = await _make_thread(
        async_db, default_user, title="Beta", issue_count=1, queue_position=2,
        read_through=1,
    )
    assert issues_a[0].issue_number == issues_b[0].issue_number
    await _confirm_identity(async_db, issues_a[0])
    await _confirm_identity(async_db, issues_b[0])
    await _thread_rate(async_db, thread_a, rating=4.5, timestamp=D1)

    audit = await audit_read_without_rating(async_db, default_user.id)
    assert audit.total == 2
    assert audit.by_cause == {
        CAUSE_MISSING_RATE_EVENT: 1,
        CAUSE_NO_SOURCE_RATING: 1,
    }

    report = await repair_safe_missing_ratings(async_db, default_user.id)
    assert report.repaired == 1
    assert report.repaired_issue_ids == [issues_a[0].id]
    events = await _issue_rate_events(async_db, issues_a[0].id)
    assert len(events) == 1
    assert events[0].rating == pytest.approx(4.5)


@pytest.mark.asyncio
async def test_repair_is_idempotent_and_preserves_existing_ratings(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Reruns insert no duplicates and never move correct latest ratings."""
    thread_a, issues_a = await _make_thread(
        async_db, default_user, title="Team Book", issue_count=1, queue_position=1,
        read_through=1,
    )
    await _confirm_identity(async_db, issues_a[0])
    await _thread_rate(async_db, thread_a, rating=4.5, timestamp=D1)
    _thread_b, issues_b = await _make_thread(
        async_db, default_user, title="Solo Book", issue_count=1, queue_position=2,
        read_through=1, first_number=2,
    )
    await _confirm_identity(async_db, issues_b[0])
    await _rate(async_db, issues_b[0], rating=3.0, timestamp=D2)

    first = await repair_safe_missing_ratings(async_db, default_user.id)
    assert first.repaired == 1

    second = await repair_safe_missing_ratings(async_db, default_user.id)
    assert second.repaired == 0
    assert second.repaired_issue_ids == []
    assert second.effective_before == 2
    assert second.effective_after == 2
    assert second.skipped_by_cause == {}

    repaired_events = await _issue_rate_events(async_db, issues_a[0].id)
    assert len(repaired_events) == 1
    assert repaired_events[0].rating == pytest.approx(4.5)
    untouched_events = await _issue_rate_events(async_db, issues_b[0].id)
    assert len(untouched_events) == 1
    assert untouched_events[0].rating == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_creator_impact_breaks_down_outlier_by_cause(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Creator impact attributes each unrated row with its own cause."""
    thread_a, issues_a = await _make_thread(
        async_db, default_user, title="Team Book", issue_count=1, queue_position=1,
        read_through=1,
    )
    await _confirm_identity(
        async_db,
        issues_a[0],
        creators=[{"id": 1, "name": "Chris Claremont", "role": "writer"}],
    )
    await _thread_rate(async_db, thread_a, rating=4.0, timestamp=D1)
    thread_b, issues_b = await _make_thread(
        async_db, default_user, title="Solo Book", issue_count=1, queue_position=2,
        read_through=1, first_number=2,
    )
    await _confirm_identity(
        async_db,
        issues_b[0],
        creators=[{"id": 1, "name": "Chris Claremont", "role": "writer"}],
    )
    _thread_c, issues_c = await _make_thread(
        async_db, default_user, title="Other Book", issue_count=1, queue_position=3,
        read_through=1, first_number=3,
    )
    await _confirm_identity(
        async_db,
        issues_c[0],
        creators=[{"id": 2, "name": "Artist Two", "role": "artist"}],
    )

    audit = await audit_read_without_rating(async_db, default_user.id)
    assert audit.total == 3
    assert audit.creator_impact[0].display_name == "Chris Claremont"
    assert audit.creator_impact[0].total == 2
    assert audit.creator_impact[0].by_cause == {
        CAUSE_MISSING_RATE_EVENT: 1,
        CAUSE_NO_SOURCE_RATING: 1,
    }
    assert {summary.display_name for summary in audit.creator_impact} == {
        "Chris Claremont",
        "Artist Two",
    }
    assert thread_b.id in audit.by_thread
    assert audit.by_thread[thread_b.id].thread_title == "Solo Book"


@pytest.mark.asyncio
async def test_drilldown_surfaces_missing_rating_cause(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The read-unrated drilldown carries the audit cause per row."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Team Book", issue_count=2, queue_position=1,
        read_through=2,
    )
    creators = [{"id": 1, "name": "Chris Claremont", "role": "writer"}]
    for issue in issues:
        await _confirm_identity(async_db, issue, creators=creators)
    await _rate(async_db, issues[0], rating=5.0, timestamp=D1)

    drilldown = await get_creator_metric_drilldown(
        async_db,
        default_user.id,
        "creator:1",
        "read-unrated-count",
    )
    assert drilldown.total_count == 1
    assert len(drilldown.included_issues) == 1
    assert drilldown.included_issues[0].issue_id == issues[1].id
    assert drilldown.included_issues[0].missing_rating_cause == CAUSE_NO_SOURCE_RATING
    assert drilldown.excluded_issues[0].missing_rating_cause is None


@pytest.mark.asyncio
async def test_empty_library_audit_is_zero(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """An empty library audits and repairs to a zero report."""
    audit = await audit_read_without_rating(async_db, default_user.id)
    assert audit.total == 0
    assert audit.by_cause == {}
    assert audit.by_thread == {}
    assert audit.creator_impact == []
    assert audit.issues == []
    assert audit.effective_rated_issues == 0

    report = await repair_safe_missing_ratings(async_db, default_user.id)
    assert report.repaired == 0
    assert report.effective_before == 0
    assert report.effective_after == 0
    assert report.skipped_by_cause == {}


@pytest.mark.asyncio
async def test_classifier_prefers_edition_conflict_over_safe_match() -> None:
    """The pure classifier never calls a duplicated row safely matchable."""
    cause = classify_missing_rating(
        issue_id=7,
        thread_id=3,
        historical_ratings=[
            ThreadHistoricalRating(
                event_id=9, thread_id=3, rating=4.5, recorded_at=D1
            )
        ],
        mapping_statuses=["confirmed"],
        duplicate_issue_ids=[11],
        unrated_read_in_thread=1,
    )
    assert cause.cause == CAUSE_EDITION_CONFLICT
    assert cause.repair_safe is False
    assert cause.source_rating is None
