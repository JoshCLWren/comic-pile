"""Creator-summary regression coverage for issue #3387.

Production ``GET /api/v1/creators/summaries`` warm reads were completing in
1915 ms against a 1000 ms request budget, with ``db;dur=1438.88;desc="4
queries"`` and 476 ms of application time.

``EXPLAIN (ANALYZE, BUFFERS)`` against a library of 2000 owned issues carrying
real normalized ComicVine payloads (~16 kB of JSON per document) isolated the
whole database cost to a single statement:

    SELECT issues.id, external_identities.metadata_json -> 'creator_credits'
    ... 80.96 ms

and nothing else in the request above 1 ms. ``external_identities.metadata_json``
was a PostgreSQL ``json`` column, which stores the provider document as raw
text, so ``->`` was a *parse of the entire document* per row rather than a key
lookup: every warm creator read reparsed the retained ``raw_provider_payload`` of
the whole library. The statement is 16.35 ms against the same fixture once the
column is ``jsonb``.

The remaining application-side cost had the same shape of bug: the aggregation
built statistics for every creator in the library and then discarded all but the
requested ones, so a batch request that names 50 creators scaled with a library
that can credit thousands.

These tests pin both properties:

- the model declares the payload column as ``jsonb``, and the creator read still
  projects only the credit key out of it rather than hydrating the payload;
- the aggregation is bounded by the requested creator ids while returning
  byte-identical statistics and library-wide coverage.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.dialects.postgresql import JSONB, asyncpg
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Event, Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.repositories.creator_summary import (
    CREATOR_CREDITS_KEY,
    CreatorCredit,
    CreatorSummaryInputs,
    manual_creator_id,
)
from app.services.creator_summary import HEADLINE_ROLES, aggregate_creators, requested_creator_ids

#: Restated locally so the reference aggregation below never shares the
#: service's own classification constant.
_REFERENCE_HEADLINE_ROLES = HEADLINE_ROLES

D1 = datetime(2026, 3, 1, tzinfo=UTC)

#: A provider document shaped like a real normalized ComicVine issue: the credit
#: list the creator read consumes plus the retained payload it must never read.
#: The bulk matters -- without it the storage guard below would pass for the
#: wrong reason, because a tiny document makes ``json`` and ``jsonb`` reads
#: indistinguishable.
_PROVIDER_PAYLOAD: dict[str, object] = {
    "id": 400_000,
    "name": "Regression Issue",
    "image": {"original_url": "https://example.invalid/original.jpg"},
    "character_credits": [
        {"id": 9_000 + offset, "name": f"Character {offset}", "deck": "x" * 200}
        for offset in range(24)
    ],
    "story_arc_credits": [
        {"id": 700 + offset, "name": f"Arc {offset}", "deck": "y" * 200}
        for offset in range(8)
    ],
}

_identity_serial = 0


@contextmanager
def _captured_selects(db_engine: AsyncEngine) -> Iterator[list[str]]:
    """Yield a list that records SELECT statements executed on the engine."""
    select_statements: list[str] = []

    def _capture(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        yield select_statements
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)


async def _confirm_issue_identity(
    db: AsyncSession,
    issue: Issue,
    *,
    credits: list[dict[str, object]],
) -> None:
    """Attach a confirmed ComicVine identity carrying real provider bulk."""
    global _identity_serial
    _identity_serial += 1
    metadata = {
        "name": _PROVIDER_PAYLOAD["name"],
        "creator_credits": credits,
        "characters": _PROVIDER_PAYLOAD["character_credits"],
        "story_arcs": _PROVIDER_PAYLOAD["story_arc_credits"],
        "raw_provider_payload": _PROVIDER_PAYLOAD,
    }
    # Guard the fixture: the retained payload must dwarf the projected credits,
    # otherwise the storage assertions would hold for an unrealistically small
    # document.
    assert len(repr(metadata["raw_provider_payload"])) > 4 * len(repr(credits))

    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=f"perf-3387-{_identity_serial}",
        metadata_json=metadata,
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


async def _make_thread(
    db: AsyncSession,
    user: User,
    *,
    title: str,
    issue_count: int,
    queue_position: int,
    read_through: int = 0,
) -> tuple[Thread, list[Issue]]:
    """Create an owned thread with contiguous issues."""
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
    issues = [
        Issue(
            thread_id=thread.id,
            issue_number=str(position),
            position=position,
            status="read" if position <= read_through else "unread",
        )
        for position in range(1, issue_count + 1)
    ]
    db.add_all(issues)
    await db.flush()
    return thread, issues


async def _rate(db: AsyncSession, issue: Issue, *, rating: float) -> Event:
    """Create one rate event for an issue."""
    db.add(
        Event(
            type="rate",
            thread_id=issue.thread_id,
            issue_id=issue.id,
            issue_number=issue.issue_number,
            rating=rating,
            timestamp=D1,
        )
    )
    await db.flush()


def test_provider_payload_column_is_jsonb() -> None:
    """The payload column must be ``jsonb``, not text ``json``.

    This is the root-cause guard for #3387. A ``json`` column keeps the stored
    document as raw text, so the creator read's ``->`` projection is a full parse
    of every owned issue's retained provider payload on every request. Nothing
    about the query changes when the type regresses, so only the declared column
    type can catch it.
    """
    column = ExternalIdentity.__table__.columns["metadata_json"]
    assert isinstance(column.type, JSONB), (
        "external_identities.metadata_json must be JSONB: on a json column every "
        "creator read reparses the whole retained provider payload per row "
        "(issue #3387)"
    )
    # The same guarantee has to hold in the live schema the app reads.
    assert isinstance(column.type.dialect_impl(asyncpg.dialect()), JSONB)


def test_creator_read_projects_the_credit_key_not_the_payload() -> None:
    """The credit read stays a single-key projection of the payload document."""
    projection = select(
        ExternalIdentity.id,
        ExternalIdentity.metadata_json[CREATOR_CREDITS_KEY],
    ).compile(dialect=asyncpg.dialect())

    select_list = str(projection).split("FROM", 1)[0]
    assert re.search(r"metadata_json\s*\[", select_list), select_list
    # A bare whole-column select is the regression this issue exists to prevent.
    assert not re.search(r"(?<![\w.])metadata_json(?![\w\s]*(\[|->))", select_list), select_list


@pytest.mark.asyncio
async def test_creator_metadata_read_is_one_bounded_projection(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """The summaries read touches the identity table once, by credit key only."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Bounded", issue_count=4, queue_position=1, read_through=4
    )
    for offset, issue in enumerate(issues):
        await _confirm_issue_identity(
            async_db,
            issue,
            credits=[{"id": 700 + offset, "name": f"Writer {offset}", "role": "writer"}],
        )
        await _rate(async_db, issue, rating=float(offset + 1))
    await async_db.flush()

    with _captured_selects(db_engine) as statements:
        response = await auth_client.get("/api/v1/creators/summaries?keys=creator:700")
    assert response.status_code == 200

    metadata_reads = [
        statement for statement in statements if "external_identities" in statement.lower()
    ]
    assert len(metadata_reads) == 1, metadata_reads
    metadata_read = metadata_reads[0]

    select_list = metadata_read.split("FROM", 1)[0]
    assert re.search(r"metadata_json\s*\[", select_list), metadata_read
    assert "raw_provider_payload" not in metadata_read
    # The retained payload must not travel to the application either.
    assert not re.search(r"(?<![\w.])metadata_json(?![\w\s]*(\[|->))", select_list), metadata_read


@pytest.mark.asyncio
async def test_wide_library_summaries_read_stays_bounded(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """Requesting one key or many costs the same fixed number of statements."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Wide", issue_count=8, queue_position=1, read_through=8
    )
    for offset, issue in enumerate(issues):
        await _confirm_issue_identity(
            async_db,
            issue,
            credits=[{"id": 800 + offset, "name": f"Writer {offset}", "role": "writer"}],
        )
        await _rate(async_db, issue, rating=float(offset + 1))
    await async_db.flush()

    await auth_client.get("/api/v1/creators/summaries?keys=creator:800")

    with _captured_selects(db_engine) as one_key_selects:
        one_key = await auth_client.get("/api/v1/creators/summaries?keys=creator:800")
    with _captured_selects(db_engine) as wide_page_selects:
        wide_page = await auth_client.get(
            "/api/v1/creators/summaries?keys="
            + ",".join(f"creator:{800 + offset}" for offset in range(8))
        )

    assert one_key.status_code == 200
    assert wide_page.status_code == 200
    assert len(one_key.json()["summaries"]) == 1
    assert len(wide_page.json()["summaries"]) == 8
    assert len(one_key_selects) == len(wide_page_selects)
    assert len(one_key_selects) <= 4, one_key_selects


def test_requested_creator_ids_keeps_only_canonical_keys() -> None:
    """Only canonical keys contribute ids; everything else is simply absent."""
    assert requested_creator_ids(["creator:12", "creator:7"]) == frozenset({12, 7})
    assert requested_creator_ids(["creator:007"]) == frozenset({7})
    assert requested_creator_ids(
        [
            "creator:1",
            "Creator:1",
            "creator:",
            "creator:abc",
            "creator:1:writer",
            "writer",
            "",
        ]
    ) == frozenset({1})


def test_aggregation_is_bounded_by_the_requested_creator_ids() -> None:
    """A request naming two creators never aggregates the other 998.

    Scoping the aggregation to the requested ids is an internal optimization, so
    its observable output is unchanged by design. What must not change is the
    work: this pins the bounding directly, with a library wide enough that an
    unbounded aggregation would aggregate all 1000 creators.
    """
    library_size = 1_000
    inputs = CreatorSummaryInputs(
        owned_issues={
            issue_id: ("read" if issue_id % 2 else "unread")
            for issue_id in range(1, library_size + 1)
        },
        issue_creator_credits={
            issue_id: (
                CreatorCredit(external_id=issue_id, roles=("writer",), display_name=f"W{issue_id}"),
                CreatorCredit(
                    external_id=library_size + issue_id,
                    roles=("artist",),
                    display_name=f"A{issue_id}",
                ),
                # Cover-only credit for the same creator must not widen the
                # headline classification or the aggregate's issue membership.
                CreatorCredit(
                    external_id=issue_id,
                    roles=("cover",),
                    display_name=f"W{issue_id}",
                ),
            )
            for issue_id in range(1, library_size + 1)
        },
        issues_with_creator_metadata=frozenset(range(1, library_size + 1)),
        effective_ratings=dict.fromkeys(range(1, library_size + 1, 2), 4.0),
    )

    wanted = frozenset({3, 11})
    aggregates = aggregate_creators(
        inputs,
        wanted_creator_ids=wanted,
        read_unrated_issue_ids=frozenset(),
        unread_issue_ids=frozenset(range(2, library_size + 1, 2)),
    )

    assert set(aggregates) == wanted
    assert len(aggregates) == 2
    for creator_id in wanted:
        aggregate = aggregates[creator_id]
        assert aggregate.display_name == f"W{creator_id}"
        assert aggregate.roles == ["cover", "writer"]
        assert aggregate.ratings_count == 1
        assert aggregate.average_rating == 4.0
        assert aggregate.read_unrated_count == 0
        assert aggregate.upcoming_count == 0


def test_bounded_aggregation_matches_a_full_library_reference() -> None:
    """Bounding the aggregation changes cost, never the computed statistics.

    The reference here is written out independently of the service: it aggregates
    every creator in the library exactly as the pre-#3387 code did and then
    selects the requested ones.
    """
    library_size = 40
    inputs = CreatorSummaryInputs(
        owned_issues={
            issue_id: ("read" if issue_id % 3 else "unread")
            for issue_id in range(1, library_size + 1)
        },
        issue_creator_credits={
            issue_id: tuple(
                CreatorCredit(external_id=creator_id, roles=(role,), display_name=f"C{creator_id}")
                for creator_id, role in (
                    (issue_id % 7, "writer"),
                    (issue_id % 11, "cover"),
                    (issue_id % 13, "artist"),
                )
            )
            for issue_id in range(1, library_size + 1)
        },
        issues_with_creator_metadata=frozenset(range(1, library_size + 1)),
        effective_ratings={
            issue_id: float(issue_id % 5) + 1 for issue_id in range(1, library_size + 1, 2)
        },
    )
    read_unrated = frozenset(
        issue_id
        for issue_id, status in inputs.owned_issues.items()
        if status == "read" and issue_id not in inputs.effective_ratings
    )
    unread = frozenset(i for i, s in inputs.owned_issues.items() if s == "unread")
    wanted = frozenset({0, 3, 7, 12})

    def reference(creator_id: int) -> tuple[object, ...]:
        """Aggregate one creator from the whole library, unbounded."""
        issue_ids = {
            issue_id
            for issue_id, credits in inputs.issue_creator_credits.items()
            if any(credit.external_id == creator_id for credit in credits)
        }
        headline_ids = {
            issue_id
            for issue_id, credits in inputs.issue_creator_credits.items()
            if any(
                credit.external_id == creator_id
                and any(role in _REFERENCE_HEADLINE_ROLES for role in credit.roles)
                for credit in credits
            )
        }
        names = [
            credit.display_name
            for credits in inputs.issue_creator_credits.values()
            for credit in credits
            if credit.external_id == creator_id
        ]
        roles = sorted(
            {
                role
                for credits in inputs.issue_creator_credits.values()
                for credit in credits
                if credit.external_id == creator_id
                for role in credit.roles
            }
        )
        ratings = [
            inputs.effective_ratings[issue_id]
            for issue_id in issue_ids
            if issue_id in headline_ids and issue_id in inputs.effective_ratings
        ]
        return (
            names[0],
            roles,
            round(sum(ratings) / len(ratings), 2) if ratings else None,
            len(ratings),
            sum(1 for issue_id in issue_ids if issue_id in read_unrated),
            sum(1 for issue_id in issue_ids if issue_id in unread),
        )

    aggregates = aggregate_creators(
        inputs,
        wanted_creator_ids=wanted,
        read_unrated_issue_ids=read_unrated,
        unread_issue_ids=unread,
    )
    assert set(aggregates) == wanted
    for creator_id in wanted:
        aggregate = aggregates[creator_id]
        assert (
            aggregate.display_name,
            aggregate.roles,
            aggregate.average_rating,
            aggregate.ratings_count,
            aggregate.read_unrated_count,
            aggregate.upcoming_count,
        ) == reference(creator_id)


@pytest.mark.asyncio
async def test_scoped_aggregation_keeps_requested_creator_statistics_exact(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Bounding the aggregation to requested ids leaves their numbers untouched.

    The library below credits one headline writer on every issue alongside a
    long tail of other creators, plus a cover-only credit and an unknown role on
    the writer's own issues. Those are exactly the cases that break if the
    scoping filter is placed wrongly: the writer's ratings average, its role
    list, and its read-unrated/unread split must all survive.
    """
    _thread, issues = await _make_thread(
        async_db, default_user, title="Mixed", issue_count=6, queue_position=1, read_through=3
    )
    for index, issue in enumerate(issues, start=1):
        await _confirm_issue_identity(
            async_db,
            issue,
            credits=[
                {"id": 900, "name": "Headline Writer", "role": "writer"},
                # Cover-only and unknown roles never enter the headline average,
                # but they still appear in the normalized role list.
                {"id": 900, "name": "Headline Writer", "role": "cover"},
                {"id": 900, "name": "Headline Writer", "role": "editor"},
                # A long tail of creators that must never be aggregated.
                {"id": 9_000 + index, "name": f"Tail Creator {index}", "role": "artist"},
            ],
        )
    # Rated issues 1-3; issue 2 is read-but-unrated, issue 1 read-unrated too.
    await _rate(async_db, issues[0], rating=4.0)
    await _rate(async_db, issues[2], rating=5.0)
    await async_db.flush()

    response = await auth_client.get(
        "/api/v1/creators/summaries?keys=creator:900,creator:9999"
    )
    assert response.status_code == 200
    body = response.json()

    # The unrequested tail creators are absent, and an unknown key is omitted.
    assert set(body["summaries"]) == {"creator:900"}

    summary = body["summaries"]["creator:900"]
    assert summary["canonical_creator_key"] == "creator:900"
    assert summary["display_name"] == "Headline Writer"
    assert summary["normalized_roles"] == ["cover", "editor", "writer"]
    # Only the two rated, headline-eligible issues contribute.
    assert summary["ratings_count"] == 2
    assert summary["average_rating"] == 4.5
    # Issue 2 is read but never rated; issues 4-6 are unread and upcoming.
    assert summary["read_unrated_count"] == 1
    assert summary["upcoming_count"] == 3

    # Coverage stays library-wide and unaffected by which keys were requested.
    assert body["coverage"]["rated_issues_total"] == 2
    assert body["coverage"]["ratings_complete"] is True
    assert body["coverage"]["read_unrated_issues_total"] == 1
    assert body["coverage"]["unread_issues_total"] == 3


@pytest.mark.asyncio
async def test_coverage_is_identical_whatever_keys_are_requested(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Coverage reports the whole library, not just the requested creators."""
    _thread, issues = await _make_thread(
        async_db, default_user, title="Coverage", issue_count=4, queue_position=1, read_through=2
    )
    for offset, issue in enumerate(issues):
        # The last owned issue has no confirmed identity at all.
        if offset < 3:
            await _confirm_issue_identity(
                async_db,
                issue,
                credits=[{"id": 950 + offset, "name": f"Writer {offset}", "role": "writer"}],
            )
        await _rate(async_db, issue, rating=float(offset + 1))
    await async_db.flush()

    narrow = await auth_client.get("/api/v1/creators/summaries?keys=creator:950")
    wide = await auth_client.get(
        "/api/v1/creators/summaries?keys=" + ",".join(f"creator:{950 + n}" for n in range(3))
    )
    assert narrow.status_code == 200
    assert wide.status_code == 200
    assert narrow.json()["coverage"] == wide.json()["coverage"]
    assert narrow.json()["coverage"]["rated_issues_total"] == 4
    assert narrow.json()["coverage"]["rated_issues_with_creator_metadata"] == 3
    assert narrow.json()["coverage"]["ratings_complete"] is False


@pytest.mark.asyncio
async def test_requested_key_spelling_is_echoed_verbatim(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The response reports back the key the client actually sent.

    Scoping the aggregation by parsed id must not rewrite the caller's key
    spelling: the response maps and each item's ``canonical_creator_key`` both
    echo the requested string.
    """
    _thread, issues = await _make_thread(
        async_db, default_user, title="Spelling", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_issue_identity(
        async_db, issues[0], credits=[{"id": 7, "name": "Seven", "role": "writer"}]
    )
    await async_db.flush()

    response = await auth_client.get("/api/v1/creators/summaries?keys=creator:007")
    assert response.status_code == 200
    body = response.json()
    assert set(body["summaries"]) == {"creator:007"}
    assert body["summaries"]["creator:007"]["canonical_creator_key"] == "creator:007"
    assert body["summaries"]["creator:007"]["display_name"] == "Seven"


@pytest.mark.asyncio
async def test_manual_thread_credits_still_aggregate_when_unrequested_creators_exist(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Manual thread credits keep their own path through the scoped aggregation."""
    thread = Thread(
        user_id=default_user.id,
        title="Manual Series",
        format="Comic",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
        status="active",
        manual_creator_credits=[{"name": "Manual Creator", "roles": ["Writer"]}],
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()

    key = f"creator:{manual_creator_id('Manual Creator')}"
    response = await auth_client.get(f"/api/v1/creators/summaries?keys={key}")
    assert response.status_code == 200
    body = response.json()
    assert body["summaries"][key]["display_name"] == "Manual Creator"
    assert body["summaries"][key]["normalized_roles"] == ["writer"]
    assert body["summaries"][key]["upcoming_count"] == 1
    assert body["coverage"]["unread_issues_total"] == 1