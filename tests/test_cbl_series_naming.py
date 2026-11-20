"""CBL materialization keeps confirmed same-named volumes distinguishable (#3547)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.thread import Thread
from app.services.cbl_plan_adoption import _ensure_missing_issue_created
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("years", "expected"),
    [
        ((1983, 2004), ("CBL: Alpha Flight (1983)", "CBL: Alpha Flight (2004)")),
        ((1983, 1983), ("CBL: Alpha Flight (1983)", "CBL: Alpha Flight (1983) (run 2)")),
        ((None, None), ("CBL: Alpha Flight", "CBL: Alpha Flight (run 2)")),
    ],
)
async def test_confirmed_runs_get_distinct_titles_and_identity_reuse(
    async_db: AsyncSession,
    years: tuple[int | None, int | None],
    expected: tuple[str, str],
) -> None:
    """Materializing two volumes keeps readable names and stable mappings on retry."""
    user = await get_or_create_user_async(async_db)
    facts: list[dict[str, object]] = []
    threads: list[Thread] = []
    issue_ids: list[int] = []
    for index, year in enumerate(years):
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="series",
            external_id=str(100 + index),
        )
        async_db.add(identity)
        await async_db.flush()
        fact: dict[str, object] = {
            "series_name": "Alpha Flight",
            "issue_number": "1",
            "external_series_identity_id": identity.id,
            "comicvine_issue_id": str(1000 + index),
        }
        facts.append(fact)
        created = await _ensure_missing_issue_created(
            async_db,
            user.id,
            fact=fact,
            volume_year=year,
        )
        assert created.created is True
        issue_ids.append(created.issue.id)
        thread = await async_db.get(Thread, created.issue.thread_id)
        assert thread is not None
        threads.append(thread)
        mapping = (
            await async_db.execute(
                select(ThreadExternalSeriesMapping).where(
                    ThreadExternalSeriesMapping.thread_id == thread.id,
                )
            )
        ).scalar_one()
        assert mapping.external_identity_id == identity.id
        assert mapping.status == "confirmed"
    assert tuple(thread.title for thread in threads) == expected
    assert threads[0].id != threads[1].id

    # A new issue from the same identity reuses the reader's renamed series.
    threads[0].title = "My Alpha Flight"
    next_fact = {**facts[0], "issue_number": "2", "comicvine_issue_id": "2000"}
    another = await _ensure_missing_issue_created(
        async_db,
        user.id,
        fact=next_fact,
        volume_year=years[0],
    )
    assert another.issue.thread_id == threads[0].id
    assert threads[0].title == "My Alpha Flight"
    for index, fact in enumerate(facts):
        repeated = await _ensure_missing_issue_created(
            async_db,
            user.id,
            fact=fact,
            volume_year=years[index],
        )
        assert repeated.created is False
        assert repeated.issue.id == issue_ids[index]


@pytest.mark.asyncio
async def test_new_volume_name_preserves_long_title_suffix_and_owner_scope(
    async_db: AsyncSession,
) -> None:
    """A year survives truncation and another reader's title does not add a suffix."""
    first = await get_or_create_user_async(async_db)
    second = await get_or_create_user_async(async_db, username="other_reader")
    name = "Alpha Flight " * 30
    expected = f"CBL: {name}"[:193].rstrip() + " (1983)"
    async_db.add(
        Thread(
            user_id=first.id,
            title=expected,
            format="comic",
            queue_position=1,
            status="active",
            created_at=datetime.now(UTC),
        )
    )
    identity = ExternalIdentity(provider="comicvine", entity_type="series", external_id="300")
    async_db.add(identity)
    await async_db.flush()
    fact: dict[str, object] = {
        "series_name": name,
        "issue_number": "1",
        "external_series_identity_id": identity.id,
        "comicvine_issue_id": "3000",
    }
    result = await _ensure_missing_issue_created(
        async_db,
        second.id,
        fact=fact,
        volume_year=1983,
    )
    thread = await async_db.get(Thread, result.issue.thread_id)
    assert thread is not None
    assert thread.title == expected
    assert len(thread.title) <= 200
    assert thread.user_id == second.id


    # A distinct confirmed volume for this same reader must preserve both suffixes.
    other_identity = ExternalIdentity(
        provider="comicvine", entity_type="series", external_id="301",
    )
    async_db.add(other_identity)
    await async_db.flush()
    collision = await _ensure_missing_issue_created(
        async_db, second.id,
        fact={**fact, "external_series_identity_id": other_identity.id,
              "comicvine_issue_id": "3001"},
        volume_year=1983,
    )
    other_thread = await async_db.get(Thread, collision.issue.thread_id)
    assert other_thread is not None
    assert other_thread.id != thread.id
    assert other_thread.title != thread.title
    assert other_thread.title.endswith(" (1983) (run 2)")
    assert len(other_thread.title) <= 200
