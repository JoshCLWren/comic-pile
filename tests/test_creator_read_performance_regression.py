"""Creator-read regression coverage for issues #3244 and #3247.

Production ``GET /api/v1/creators`` warm reads were taking 1.4-2.0 seconds, and
the per-creator ``GET /api/v1/creators/creator:<id>`` read retained a 1337.60 ms
log line. Avoidable costs fed that budget:

1. (#3244) the confirmed-identity read hydrated the whole normalized ComicVine
   issue metadata for every owned issue, even though the creator read only
   consumes ``creator_credits`` — the rest of that document is the retained
   ``raw_provider_payload``;
2. (#3244) the effective-rating read collapsed rate events in Python and
   spelled ``DISTINCT ON`` through the deprecated ``distinct(<expression>)``
   argument, which emits ``SADeprecationWarning`` on the pinned SQLAlchemy 2.1;
3. (#3247) the creator detail read re-filtered every owned issue's creator
   credits once per aggregate — headline eligibility, each role statistic, the
   series/run grouping, and every built issue row — so the route cost scale as
   roles x attributed issues x credits per request;
4. (#3247) an empty rated/read-but-unrated/upcoming collection still paid a
   database round trip for an empty ``IN`` filter.

These tests pin all four properties so a read cannot quietly regress onto
hydrating full provider payloads, onto a deprecated SQLAlchemy call, onto
repeated per-role credit scans, or onto empty-collection round trips, and so
the projected read provably returns identical creator semantics to the
full-metadata read it replaced.
"""

import inspect
import re
import time
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.comicvine_hydration import normalize_issue
from app.models import Event, Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.repositories.creator_summary import (
    CREATOR_CREDITS_KEY,
    CreatorCredit,
    CreatorSummaryInputs,
    extract_creator_credit_list,
    extract_creator_credits,
)
from app.services import creator_detail as creator_detail_service
from app.services import creator_series as creator_series_service
from app.services.creator_detail import resolve_creator_issues
from app.services.creator_series import aggregate_creator_series_groups
from app.services.creator_summary import build_creator_attribution

D1 = datetime(2026, 3, 1, tzinfo=UTC)

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


def _provider_issue_result(issue_number: int, person_ids: list[int]) -> dict[str, object]:
    """Build a ComicVine-shaped singular issue payload with real payload bulk.

    The character and story-arc credit lists stand in for the parts of
    ``raw_provider_payload`` a creator read never needs. Without them the stored
    metadata would be small enough that the projection guard proved nothing.
    """
    return {
        "id": 100_000 + issue_number,
        "name": f"Bench Issue {issue_number}",
        "issue_number": str(issue_number),
        "cover_date": "2026-01-01",
        "site_detail_url": f"https://comicvine.gamespot.com/issue/4000-{100_000 + issue_number}/",
        "image": {
            "original_url": "https://example.invalid/original.jpg",
            "super_url": "https://example.invalid/super.jpg",
            "medium_url": "https://example.invalid/medium.jpg",
            "small_url": "https://example.invalid/small.jpg",
        },
        "volume": {
            "id": 5_000 + issue_number % 50,
            "name": f"Volume {issue_number % 50}",
            "api_detail_url": "https://comicvine.gamespot.com/api/volume/4050-5000/",
            "site_detail_url": "https://comicvine.gamespot.com/volume/4000-5000/",
        },
        "person_credits": [
            {
                "id": person_id,
                "name": f"Creator {person_id}",
                "api_detail_url": f"https://comicvine.gamespot.com/api/person/1-{person_id}/",
                "site_detail_url": (
                    f"https://comicvine.gamespot.com/person/4000-{person_id}/"
                ),
                "role": role,
            }
            for person_id, role in zip(person_ids, ("writer", "penciler"), strict=False)
        ],
        "character_credits": [
            {
                "id": 9_000 + offset,
                "name": f"Character {offset}",
                "api_detail_url": (
                    f"https://comicvine.gamespot.com/api/character/4005-{9_000 + offset}/"
                ),
                "site_detail_url": (
                    f"https://comicvine.gamespot.com/character/4000-{9_000 + offset}/"
                ),
            }
            for offset in range(24)
        ],
        "story_arc_credits": [
            {
                "id": 700 + offset,
                "name": f"Arc {offset}",
                "api_detail_url": "https://comicvine.gamespot.com/api/story_arc/4045-700/",
                "site_detail_url": (
                    f"https://comicvine.gamespot.com/story-arc/4000-{700 + offset}/"
                ),
            }
            for offset in range(8)
        ],
    }


async def _seed_full_payload_library(
    db: AsyncSession,
    user: User,
    *,
    thread_count: int,
    issues_per_thread: int,
) -> tuple[Thread, list[Issue]]:
    """Create owned issues whose confirmed identities carry full provider payloads."""
    global _identity_serial

    threads: list[Thread] = []
    issues: list[Issue] = []
    for thread_index in range(1, thread_count + 1):
        thread = Thread(
            user_id=user.id,
            title=f"Series {thread_index}",
            format="Comic",
            issues_remaining=issues_per_thread,
            total_issues=issues_per_thread,
            queue_position=thread_index,
            status="active",
        )
        db.add(thread)
        await db.flush()
        threads.append(thread)
        for position in range(1, issues_per_thread + 1):
            issue = Issue(
                thread_id=thread.id,
                issue_number=str(position),
                position=position,
                status="read",
            )
            db.add(issue)
            await db.flush()
            issues.append(issue)

            _identity_serial += 1
            person_id = 400 + thread_index * 2
            metadata = normalize_issue(
                _provider_issue_result(_identity_serial, [person_id, person_id + 1])
            )
            # Guard the fixture: the payload must actually be larger than the
            # projected creator credits, otherwise the projection assertions below
            # would pass for the wrong reason.
            assert "raw_provider_payload" in metadata
            assert len(repr(metadata)) > 4 * len(repr(metadata[CREATOR_CREDITS_KEY]))

            identity = ExternalIdentity(
                provider="comicvine",
                entity_type="issue",
                external_id=f"perf-{_identity_serial}",
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
            for version in range(3):
                db.add(
                    Event(
                        type="rate",
                        thread_id=thread.id,
                        issue_id=issue.id,
                        issue_number=issue.issue_number,
                        rating=float(1 + version),
                        timestamp=datetime(2026, 3, version + 1, tzinfo=UTC),
                    )
                )
    await db.flush()
    return threads[0], issues


@pytest.mark.asyncio
async def test_creator_metadata_read_projects_only_creator_credits(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """The confirmed-identity read fetches the credit list, not the whole payload.

    Hydrating ``metadata_json`` in full pulled the retained ComicVine
    ``raw_provider_payload`` over the wire and into Python for every owned issue
    on every creator read. Only the JSON key projection is allowed now.
    """
    await _seed_full_payload_library(async_db, default_user, thread_count=2, issues_per_thread=2)
    await async_db.flush()

    with _captured_selects(db_engine) as statements:
        response = await auth_client.get("/api/v1/creators")
    assert response.status_code == 200

    metadata_reads = [
        statement for statement in statements if "external_identities" in statement.lower()
    ]
    assert len(metadata_reads) == 1, metadata_reads
    metadata_read = metadata_reads[0]

    # The projection is applied in SQL, so the provider payload never leaves PostgreSQL.
    assert re.search(r"metadata_json\s*->", metadata_read), metadata_read
    assert "raw_provider_payload" not in metadata_read
    # A bare whole-column select is the regression this issue exists to prevent.
    select_list = metadata_read.split("FROM", 1)[0]
    assert not re.search(r"(?<![\w.])metadata_json(?![\w\s]*->)", select_list.split("SELECT", 1)[1])


@pytest.mark.asyncio
async def test_effective_rating_read_uses_distinct_on_without_deprecation(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """Rate events collapse with ``DISTINCT ON`` and without a SQLAlchemy deprecation.

    ``distinct(Event.issue_id)`` renders the same SQL but is deprecated on
    SQLAlchemy 2.1 and raises ``SADeprecationWarning`` on every creator read.
    """
    _thread, issues = await _seed_full_payload_library(
        async_db, default_user, thread_count=2, issues_per_thread=2
    )
    await async_db.flush()

    with _captured_selects(db_engine) as statements:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            response = await auth_client.get("/api/v1/creators")
    assert response.status_code == 200

    rate_reads = [statement for statement in statements if "DISTINCT ON" in statement.upper()]
    assert len(rate_reads) == 1, statements

    deprecations = [
        entry
        for entry in caught
        if entry.category.__name__ == "SADeprecationWarning" and "distinct" in str(entry.message)
    ]
    assert deprecations == []


@pytest.mark.asyncio
async def test_projected_read_matches_full_metadata_creator_semantics(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Projected creator credits match a full-document extraction of the same metadata.

    Both readers must agree on keys, display names, roles, counts, averages and
    coverage. ``extract_creator_credits`` keeps reading a whole metadata document
    for callers that hold one; the repository read projects the same list.
    """
    thread_count = 3
    issues_per_thread = 2
    _thread, issues = await _seed_full_payload_library(
        async_db, default_user, thread_count=thread_count, issues_per_thread=issues_per_thread
    )
    await async_db.flush()

    response = await auth_client.get("/api/v1/creators?limit=50")
    assert response.status_code == 200
    body = response.json()
    assert len(issues) == thread_count * issues_per_thread
    assert body["total"] == thread_count * 2
    assert body["coverage"]["rated_issues_total"] == len(issues)
    assert body["coverage"]["ratings_complete"] is True

    expected_keys = {
        f"creator:{person_id}" for person_id in range(402, 402 + thread_count * 2)
    }
    assert {row["canonical_creator_key"] for row in body["items"]} == expected_keys

    stored_rows = await async_db.execute(
        select(ExternalIdentity.metadata_json).where(
            ExternalIdentity.external_id.like("perf-%")
        )
    )
    checked = 0
    for (metadata,) in stored_rows.all():
        assert isinstance(metadata, dict)
        assert "raw_provider_payload" in metadata
        assert extract_creator_credits(metadata) == extract_creator_credit_list(
            metadata[CREATOR_CREDITS_KEY]
        )
        assert extract_creator_credit_list(metadata[CREATOR_CREDITS_KEY])
        checked += 1
    assert checked == len(issues)


@pytest.mark.asyncio
async def test_wide_library_creator_read_stays_bounded(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """A wide library still costs a fixed number of SELECTs with full payloads."""
    await _seed_full_payload_library(async_db, default_user, thread_count=8, issues_per_thread=5)
    await async_db.flush()

    await auth_client.get("/api/v1/creators")

    with _captured_selects(db_engine) as small_page:
        small = await auth_client.get("/api/v1/creators?limit=1&offset=0")
    with _captured_selects(db_engine) as full_page:
        full = await auth_client.get("/api/v1/creators?limit=50&offset=0")

    assert small.status_code == 200
    assert full.status_code == 200
    assert len(small.json()["items"]) == 1
    assert full.json()["total"] == 16
    assert len(small_page) == len(full_page)
    assert len(small_page) <= 5, small_page


@pytest.mark.asyncio
async def test_thread_read_is_one_user_scoped_statement(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """Thread titles and manual credits are read once per thread, not per issue.

    Projecting those columns off the issue join repeated the stored manual-credit
    document on every owned issue row, so a wide library moved the same JSON once
    per issue (issue #3387). The read that replaced it must stay a single
    thread-only statement scoped by the indexed ``threads.user_id`` predicate:
    filtering the same rows by a library-sized ``id IN (...)`` list would
    reintroduce the wide-library cost this read exists to remove.
    """
    await _seed_full_payload_library(async_db, default_user, thread_count=8, issues_per_thread=5)
    await async_db.flush()

    # The fixture credits person ids 402 and 403 on its first thread, so both
    # requested keys resolve and the response proves the read still works.
    with _captured_selects(db_engine) as statements:
        response = await auth_client.get("/api/v1/creators/summaries?keys=creator:402,creator:403")
    assert response.status_code == 200
    assert len(response.json()["summaries"]) == 2

    thread_reads = [
        statement for statement in statements if "manual_creator_credits" in statement.lower()
    ]
    assert len(thread_reads) == 1, thread_reads
    thread_read = thread_reads[0]
    assert "threads.user_id" in thread_read, thread_read
    # Thread-only: no issue join, so no duplicated row per owned issue.
    assert " JOIN " not in thread_read.upper(), thread_read
    # User-scoped predicate only; never one bind parameter per owned thread.
    assert not re.search(r"\bIN\s*\(", thread_read, flags=re.IGNORECASE), thread_read


def test_extract_creator_credit_list_rejects_unusable_values() -> None:
    """Only a list of credit dictionaries yields credits."""
    assert extract_creator_credit_list(None) == []
    assert extract_creator_credit_list("nope") == []
    assert extract_creator_credit_list({"id": 1}) == []
    assert extract_creator_credit_list([{"name": "No id"}, "not a dict"]) == []
    assert extract_creator_credit_list([{"id": 1, "name": "  "}]) == []
    assert extract_creator_credit_list([{"id": "12", "name": "String id"}])[0].external_id == 12


def test_extract_creator_credit_list_deduplicates_and_sorts_roles() -> None:
    """Distinct (creator, role-set) pairs survive with comma-joined roles split."""
    credits = extract_creator_credit_list(
        [
            {"id": 7, "name": "Seven", "role": "penciler, writer"},
            {"id": 7, "name": "Seven", "role": "penciler,writer"},
            {"id": 7, "name": "Seven"},
            {"id": 7, "name": "Seven", "role": "inker"},
        ]
    )
    assert [(credit.external_id, credit.roles, credit.display_name) for credit in credits] == [
        (7, ("penciler", "writer"), "Seven"),
        (7, (), "Seven"),
        (7, ("inker",), "Seven"),
    ]


def test_extract_creator_credits_reads_the_named_key() -> None:
    """The whole-document reader stays a thin wrapper over the list reader."""
    raw = [{"id": 3, "name": "Three", "role": "writer"}]
    assert extract_creator_credits({CREATOR_CREDITS_KEY: raw}) == extract_creator_credit_list(raw)
    assert extract_creator_credits({"other": raw}) == []


# ---------------------------------------------------------------------------
# Issue #3247: creator-detail warm-read latency
# ---------------------------------------------------------------------------

#: A creator credited with exactly one role on every owned issue.
SINGLE_ROLE_CREATOR = 61_001

#: A creator credited with six roles on every owned issue, so per-role work is
#: the only thing that differs from :data:`SINGLE_ROLE_CREATOR`.
MULTI_ROLE_CREATOR = 61_002

#: Role credit that normalizes to six distinct roles.
MULTI_ROLE_CREDIT = "writer,penciler,inker,colorist,letterer,artist"

#: Filler creators, so every issue carries a realistic multi-creator credit list
#: instead of only the two creators under test.
FILLER_CREATORS = (71_001, 71_002, 71_003)


async def _seed_attribution_library(
    db: AsyncSession,
    user: User,
    *,
    thread_count: int,
    issues_per_thread: int,
    read_through: int,
    rated_through: int,
    credits: dict[int, tuple[str, int]],
) -> list[Issue]:
    """Create an owned library whose issues carry production-shaped credits.

    Issue positions ``1..rated_through`` are read and rated, positions
    ``rated_through + 1..read_through`` are read but unrated, and the rest are
    unread. ``credits`` maps a creator id to the role string it is credited
    with and the last issue position it is credited on, so one creator can own
    only rated work while another owns rated, read-but-unrated, and upcoming
    work in the same library.

    Args:
        db: Async database session.
        user: Owner of the seeded library.
        thread_count: Number of owned threads.
        issues_per_thread: Contiguous issues created per thread.
        read_through: Last issue position marked ``read``.
        rated_through: Last issue position given an effective rating.
        credits: Creator id to (role string, last credited issue position).

    Returns:
        Every seeded issue in creation order.
    """
    global _identity_serial

    seeded: list[Issue] = []
    for thread_index in range(1, thread_count + 1):
        thread = Thread(
            user_id=user.id,
            title=f"Attribution Series {thread_index}",
            format="Comic",
            issues_remaining=issues_per_thread - read_through,
            total_issues=issues_per_thread,
            queue_position=thread_index,
            status="active",
        )
        db.add(thread)
        await db.flush()
        for position in range(1, issues_per_thread + 1):
            issue = Issue(
                thread_id=thread.id,
                issue_number=str(position),
                position=position,
                status="read" if position <= read_through else "unread",
            )
            db.add(issue)
            await db.flush()
            seeded.append(issue)

            person_credits: list[dict[str, object]] = [
                {
                    "id": creator_id,
                    "name": f"Creator {creator_id}",
                    "api_detail_url": (
                        f"https://comicvine.gamespot.com/api/person/1-{creator_id}/"
                    ),
                    "site_detail_url": (
                        f"https://comicvine.gamespot.com/person/4000-{creator_id}/"
                    ),
                    "role": role,
                }
                for creator_id, (role, last_position) in credits.items()
                if position <= last_position
            ]
            person_credits.extend(
                {
                    "id": filler_id,
                    "name": f"Filler {filler_id}",
                    "api_detail_url": (
                        f"https://comicvine.gamespot.com/api/person/1-{filler_id}/"
                    ),
                    "site_detail_url": (
                        f"https://comicvine.gamespot.com/person/4000-{filler_id}/"
                    ),
                    "role": "cover",
                }
                for filler_id in FILLER_CREATORS
            )

            _identity_serial += 1
            provider_result = _provider_issue_result(_identity_serial, [])
            provider_result["person_credits"] = person_credits
            metadata = normalize_issue(provider_result)
            identity = ExternalIdentity(
                provider="comicvine",
                entity_type="issue",
                external_id=f"perf-{_identity_serial}",
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
            if position <= rated_through:
                db.add(
                    Event(
                        type="rate",
                        thread_id=thread.id,
                        issue_id=issue.id,
                        issue_number=issue.issue_number,
                        rating=float(1 + (position % 5)),
                        timestamp=D1,
                    )
                )
    await db.flush()
    return seeded


def test_detail_path_never_re_filters_raw_credit_lists() -> None:
    """Creator detail reads credit lists only through the attribution index.

    This is the static guard for the dominant cost in #3247. Every aggregate
    used to re-run ``for credit in inputs.issue_creator_credits[...]`` on its
    own, so the read cost roles x attributed issues x credits. The raw mapping
    must now appear nowhere in the detail service, and the series aggregation
    must read roles from the prebuilt attribution instead of re-deriving them.
    """
    assert "issue_creator_credits" not in inspect.getsource(creator_detail_service)

    aggregate_source = inspect.getsource(aggregate_creator_series_groups)
    assert "issue_creator_credits" not in aggregate_source
    assert "creator_roles_on_issue" not in aggregate_source


def test_attribution_index_matches_the_legacy_resolution() -> None:
    """The one-pass index returns exactly what the repeated scans returned."""
    inputs = CreatorSummaryInputs(
        owned_issues={1: "read", 2: "unread", 3: "read"},
        owned_issue_series={},
        issue_creator_credits={
            1: (
                CreatorCredit(external_id=9, roles=("writer",), display_name="Nine"),
                CreatorCredit(external_id=4, roles=("cover",), display_name="Four"),
            ),
            # A confirmed credit with no role at all still attributes the issue.
            2: (CreatorCredit(external_id=9, roles=(), display_name="Nine"),),
            3: (
                CreatorCredit(external_id=9, roles=("penciler", "artist"), display_name="Nine"),
                CreatorCredit(external_id=9, roles=("writer",), display_name="Nine"),
            ),
        },
    )

    issue_ids, roles, display_name = resolve_creator_issues(inputs, creator_id=9)
    attribution = build_creator_attribution(inputs, creator_id=9)

    assert attribution.issue_ids == issue_ids == frozenset({1, 2, 3})
    assert attribution.roles == frozenset(roles) == frozenset({"artist", "penciler", "writer"})
    assert attribution.display_name == display_name == "Nine"
    # Roles are stored sorted per issue, exactly like ``creator_roles_on_issue``.
    assert attribution.issue_roles == {
        1: ("writer",),
        2: (),
        3: ("artist", "penciler", "writer"),
    }
    assert resolve_creator_issues(inputs, creator_id=4)[0] == frozenset({1})


def test_attribution_index_rejects_a_creator_outside_the_library() -> None:
    """A creator with no confirmed credit is still not found."""
    inputs = CreatorSummaryInputs(
        issue_creator_credits={1: (CreatorCredit(external_id=9, roles=("writer",)),)},
    )
    with pytest.raises(KeyError):
        build_creator_attribution(inputs, creator_id=404)


@pytest.mark.asyncio
async def test_detail_read_never_re_derives_per_issue_roles(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-issue role re-derivation helper is off the creator detail path.

    ``creator_roles_on_issue`` scans one issue's stored credits, so calling it
    once per attributed issue made the series/run grouping cost scale with the
    creator's library. Replacing it with a call that raises proves the fixed
    path never reaches it.
    """

    def _forbidden(*args: object, **kwargs: object) -> list[str]:
        raise AssertionError("creator detail must not re-derive per-issue roles")

    monkeypatch.setattr(creator_series_service, "creator_roles_on_issue", _forbidden)

    await _seed_attribution_library(
        async_db,
        default_user,
        thread_count=3,
        issues_per_thread=6,
        read_through=6,
        rated_through=3,
        credits={
            MULTI_ROLE_CREATOR: (MULTI_ROLE_CREDIT, 6),
            SINGLE_ROLE_CREATOR: ("writer", 6),
        },
    )

    response = await auth_client.get(f"/api/v1/creators/creator:{MULTI_ROLE_CREATOR}")
    assert response.status_code == 200
    assert response.json()["series_groups"]


@pytest.mark.asyncio
async def test_detail_read_skips_queries_for_empty_collections(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """An empty collection short-circuits instead of round-tripping on ``IN ()``.

    A creator with rated work only has no read-but-unrated and no upcoming
    issues. The other creator in the same library has all three collections
    populated, so the rated-only read must issue strictly fewer SELECTs. Each
    avoided round trip is latency the read no longer spends. Before the fix both
    reads issued the same number of SELECTs because the empty collections still
    round-tripped.
    """
    issues_per_thread = 6
    await _seed_attribution_library(
        async_db,
        default_user,
        thread_count=3,
        issues_per_thread=issues_per_thread,
        read_through=issues_per_thread - 2,
        rated_through=2,
        credits={
            # Rated work only: no read-but-unrated, no upcoming.
            SINGLE_ROLE_CREATOR: ("writer", 2),
            # Rated, read-but-unrated, and upcoming work.
            MULTI_ROLE_CREATOR: ("writer", issues_per_thread),
        },
    )

    await auth_client.get(f"/api/v1/creators/creator:{SINGLE_ROLE_CREATOR}")

    with _captured_selects(db_engine) as rated_only:
        rated_only_response = await auth_client.get(
            f"/api/v1/creators/creator:{SINGLE_ROLE_CREATOR}"
        )
    with _captured_selects(db_engine) as full_shapes:
        full_response = await auth_client.get(f"/api/v1/creators/creator:{MULTI_ROLE_CREATOR}")

    assert rated_only_response.status_code == 200
    assert full_response.status_code == 200

    body = rated_only_response.json()
    assert body["summary"]["ratings_count"] > 0
    assert body["summary"]["read_unrated_count"] == 0
    assert body["summary"]["upcoming_count"] == 0

    assert len(rated_only) < len(full_shapes), (len(rated_only), len(full_shapes))
    # Auth lookup, four aggregation reads, the rated page, and rating timestamps.
    assert len(rated_only) <= 7, rated_only


@pytest.mark.asyncio
async def test_warm_detail_read_is_fast_for_a_prolific_creator(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A warm creator-detail read stays prompt on production-shaped data.

    Production logged 1337.60 ms for ``GET /api/v1/creators/creator:42389``.
    This seeds a library whose issues carry real ComicVine payload bulk and a
    six-role creator, warms the connection and statement caches, then asserts
    the warm read still returns well inside a generous bound. The ceiling is a
    catastrophic-regression guard for shared CI hardware; the 500 ms product
    budget is measured against production logs, not this fixture.
    """
    thread_count = 10
    issues_per_thread = 20
    issues = await _seed_attribution_library(
        async_db,
        default_user,
        thread_count=thread_count,
        issues_per_thread=issues_per_thread,
        read_through=issues_per_thread,
        rated_through=issues_per_thread,
        credits={
            MULTI_ROLE_CREATOR: (MULTI_ROLE_CREDIT, issues_per_thread),
            SINGLE_ROLE_CREATOR: ("writer", issues_per_thread),
        },
    )

    # Warm-up: connection pool, prepared statements, and page cache.
    for _ in range(2):
        warm = await auth_client.get(f"/api/v1/creators/creator:{MULTI_ROLE_CREATOR}")
        assert warm.status_code == 200

    timings: list[float] = []
    for _ in range(3):
        started = time.perf_counter()
        response = await auth_client.get(f"/api/v1/creators/creator:{MULTI_ROLE_CREATOR}")
        timings.append(time.perf_counter() - started)
        assert response.status_code == 200

    body = response.json()
    assert body["summary"]["ratings_count"] == len(issues)
    assert body["series_groups_total"] == thread_count
    assert {stat["role"] for stat in body["role_stats"]} == {
        "artist",
        "colorist",
        "inker",
        "letterer",
        "penciler",
        "writer",
    }
    assert max(timings) < 5, timings
