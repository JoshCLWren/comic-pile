"""Creator-read regression coverage for issue #3244.

Production ``GET /api/v1/creators`` warm reads were taking 1.4-2.0 seconds. Two
avoidable costs in ``load_creator_summary_inputs`` fed that budget:

1. the confirmed-identity read hydrated the whole normalized ComicVine issue
   metadata for every owned issue, even though the creator read only consumes
   ``creator_credits`` — the rest of that document is the retained
   ``raw_provider_payload``;
2. the effective-rating read collapsed rate events in Python and spelled
   ``DISTINCT ON`` through the deprecated ``distinct(<expression>)`` argument,
   which emits ``SADeprecationWarning`` on the pinned SQLAlchemy 2.1.

These tests pin both properties so the read cannot quietly regress back to
hydrating full provider payloads or onto a deprecated SQLAlchemy call, and so
the projected read provably returns identical creator semantics to the
full-metadata read it replaced.
"""

import re
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
    extract_creator_credit_list,
    extract_creator_credits,
)

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
    assert len(small_page) <= 4, small_page


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
