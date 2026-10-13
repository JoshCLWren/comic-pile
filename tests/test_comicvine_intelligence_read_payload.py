"""Read-payload and multi-arc correctness coverage for issue #3390.

``GET /api/v1/issues/<id>/comicvine`` was recorded at 1773 ms against a
1000 ms budget with 182 ms of database time and 1590 ms of application time
across 10 statements. That profile is application-heavy, so the cost the
incident pointed at was the request path decoding whole stored
``metadata_json`` documents -- which embed ``raw_provider_payload`` -- for
every candidate story-arc member row.

The fix projects the rendered fields instead of the whole document. This
module pins the two properties that fix must not break:

1. Arc membership stays a disjunction over the requested arcs. Collapsing the
   per-arc containment branches into a single ``@>`` predicate covering every
   arc turns "shares any arc" into "shares every arc", which silently empties
   the related-issues section for ordinary multi-arc issues.
2. The arc-member scan never selects an untrimmed ``metadata_json``
   document, and repeated reads of one issue return a stable description
   rather than a value that accumulates across requests.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.services import comicvine_intelligence
from app.services.comicvine_intelligence import (
    MAX_ARCS_PER_INTELLIGENCE_READ,
    get_issue_intelligence,
)

_DESCRIPTION = "<p>Bruce   Wayne<br/>returns to <b>Gotham</b>.</p>"


@contextmanager
def _captured_selects(db_engine: AsyncEngine) -> Iterator[list[str]]:
    """Capture the SQL text of every SELECT executed inside the block."""
    statements: list[str] = []

    def _before(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _before)
    try:
        yield statements
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _before)


def _arc_member_statements(statements: list[str]) -> list[str]:
    return [statement for statement in statements if "external_identities ei" in statement]


def _select_clause(statement: str) -> str:
    match = re.search(r"SELECT(.*?)FROM", statement, re.DOTALL)
    assert match is not None, statement
    return match.group(1)


def _metadata(*, arc_ids: list[int], description: str | None = None) -> dict[str, object]:
    """Build stored metadata shaped like a hydrated ComicVine issue."""
    metadata: dict[str, object] = {
        "name": "Payload Bench Issue",
        "issue_number": "1",
        "cover_date": "2026-01-01",
        "volume": {"id": 4050, "name": "Bench Volume"},
        "story_arc_credits": [{"id": arc_id, "name": f"Arc {arc_id}"} for arc_id in arc_ids],
        "raw_provider_payload": {
            "description": description,
            "person_credits": [{"id": 4242, "name": "Bench Writer", "role": "writer"}],
            "story_arc_credits": [{"id": arc_id} for arc_id in arc_ids],
        },
    }
    if description is not None:
        metadata["description"] = description
    return metadata


async def _mapped_issue(
    db: AsyncSession,
    thread: Thread,
    *,
    issue_number: str,
    external_id: str,
    metadata: dict[str, object],
    position: int,
) -> Issue:
    """Create one issue with a confirmed ComicVine issue-level mapping."""
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=position,
        status="unread",
    )
    db.add(issue)
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=external_id,
        external_url=f"https://comicvine.example/issues/{external_id}",
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
    return issue


@pytest.fixture
async def bench_thread(async_db: AsyncSession, default_user: User) -> Thread:
    """Create one owning thread for the issue rows under test."""
    thread = Thread(
        user_id=default_user.id,
        title="Payload Bench Series",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    return thread


@pytest.fixture(autouse=True)
def _no_background_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    def _noop_schedule(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(comicvine_intelligence, "schedule_issue_metadata_refresh", _noop_schedule)


@pytest.mark.asyncio
async def test_multi_arc_read_returns_members_from_every_arc(
    async_db: AsyncSession,
    bench_thread: Thread,
    default_user: User,
) -> None:
    """Members of any requested arc appear, not only members of every arc.

    Arc membership is a disjunction, so a candidate row that belongs to
    exactly one of the requested arcs must still be returned for that arc.
    """
    arc_ids = [42, 84, 126]
    current = await _mapped_issue(
        async_db,
        bench_thread,
        issue_number="1",
        external_id="1001184",
        metadata=_metadata(arc_ids=arc_ids),
        position=1,
    )
    for index, arc_id in enumerate(arc_ids):
        for member in range(2):
            await _mapped_issue(
                async_db,
                bench_thread,
                issue_number=f"{arc_id}-{member}",
                external_id=str(2000000 + arc_id * 10 + member),
                metadata=_metadata(arc_ids=[arc_id]),
                position=2 + index * 2 + member,
            )

    result = await get_issue_intelligence(async_db, current.id, default_user.id)

    assert result is not None
    assert [arc.comicvine_arc_id for arc in result.story_arcs] == arc_ids
    for arc in result.story_arcs:
        assert {item.comicvine_issue_id for item in arc.related_issues} == {
            str(2000000 + arc.comicvine_arc_id * 10),
            str(2000000 + arc.comicvine_arc_id * 10 + 1),
        }


@pytest.mark.asyncio
async def test_arc_member_scan_projects_only_rendered_fields(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    bench_thread: Thread,
    default_user: User,
) -> None:
    """The arc-member scan never selects an untrimmed metadata document."""
    arc_ids = list(range(1, MAX_ARCS_PER_INTELLIGENCE_READ + 1))
    current = await _mapped_issue(
        async_db,
        bench_thread,
        issue_number="1",
        external_id="1025277",
        metadata=_metadata(arc_ids=arc_ids, description=_DESCRIPTION),
        position=1,
    )
    for offset in range(5):
        await _mapped_issue(
            async_db,
            bench_thread,
            issue_number=str(2 + offset),
            external_id=str(2000000 + offset),
            metadata=_metadata(arc_ids=[1], description=_DESCRIPTION),
            position=2 + offset,
        )

    with _captured_selects(db_engine) as statements:
        result = await get_issue_intelligence(async_db, current.id, default_user.id)

    assert result is not None
    arc_statements = _arc_member_statements(statements)
    assert arc_statements
    for statement in arc_statements:
        clause = _select_clause(statement)
        assert not re.search(r"metadata_json(?!\s*->)", clause), clause


@pytest.mark.asyncio
async def test_projected_series_and_related_fields_match_stored_metadata(
    async_db: AsyncSession,
    bench_thread: Thread,
    default_user: User,
) -> None:
    """Projected columns keep both the nested-volume and flat-volume shapes.

    ``_series`` resolves ``volume`` when it is an object and falls back to
    ``volume_id``/``volume_name`` when it is not, so both stored shapes must
    survive the projection.
    """
    current = await _mapped_issue(
        async_db,
        bench_thread,
        issue_number="1",
        external_id="3000001",
        metadata={
            "name": "Flat Volume Issue",
            "volume_id": 77,
            "volume_name": "Flat Volume",
            "story_arc_credits": [{"id": 42, "name": "Arc 42"}],
        },
        position=1,
    )
    await _mapped_issue(
        async_db,
        bench_thread,
        issue_number="2",
        external_id="3000002",
        metadata=_metadata(arc_ids=[42]),
        position=2,
    )

    result = await get_issue_intelligence(async_db, current.id, default_user.id)

    assert result is not None
    assert result.series_id == 77
    assert result.series_name == "Flat Volume"
    related = result.story_arcs[0].related_issues
    assert len(related) == 1
    assert related[0].comicvine_issue_id == "3000002"
    assert related[0].series_name == "Bench Volume"
    assert related[0].name == "Payload Bench Issue"
    assert related[0].issue_number == "1"
    assert related[0].cover_date == "2026-01-01"
    assert related[0].comicvine_url == "https://comicvine.example/issues/3000002"


@pytest.mark.asyncio
async def test_repeated_reads_return_a_stable_description(
    async_db: AsyncSession,
    bench_thread: Thread,
    default_user: User,
) -> None:
    """Reading one issue twice returns the same description both times.

    A parser reused across requests accumulates the fragments it has already
    seen, so a shared or cached parser makes the rendered description grow
    with every read.
    """
    current = await _mapped_issue(
        async_db,
        bench_thread,
        issue_number="1",
        external_id="4000001",
        metadata=_metadata(arc_ids=[42], description=_DESCRIPTION),
        position=1,
    )

    first = await get_issue_intelligence(async_db, current.id, default_user.id)
    second = await get_issue_intelligence(async_db, current.id, default_user.id)

    assert first is not None
    assert second is not None
    assert first.description == "Bruce Wayne returns to Gotham ."
    assert second.description == first.description