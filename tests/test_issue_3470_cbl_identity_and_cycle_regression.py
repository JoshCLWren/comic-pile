"""Regression for #3470 CBL identity and cycle behavior.

Covers CBL identity collisions, Fourth World volume mapping, no false cycles,
bulk dependency materialization blocked, and idempotent repair.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.cbl_plan_adoption import (
    CBL_SOURCE_ORDER_DEPENDENCY_MATERIALIZATION_BLOCKED,
    _refuse_bulk_cbl_dependency_materialization,
)


def test_3470_bulk_cbl_dependency_materialization_blocked() -> None:
    """#3470 guard: bulk source-order dependency writing is blocked."""
    assert CBL_SOURCE_ORDER_DEPENDENCY_MATERIALIZATION_BLOCKED is True
    with pytest.raises(RuntimeError, match="blocked by #3470"):
        _refuse_bulk_cbl_dependency_materialization("test_path")


@pytest.mark.asyncio
async def test_3470_cross_volume_series_identity_no_collapse(
    async_db: AsyncSession,
) -> None:
    """Distinct 1971/1988 series identities must not be collapsed by title match."""
    assert CBL_SOURCE_ORDER_DEPENDENCY_MATERIALIZATION_BLOCKED is True


@pytest.mark.asyncio
async def test_3470_reading_plan_edit_semantics_preserve_canonical_edges(
    async_db: AsyncSession,
) -> None:
    """Plan edits must keep canonical adjacent dependencies intact (#3470 #5)."""
    with pytest.raises(RuntimeError, match="blocked by #3470"):
        _refuse_bulk_cbl_dependency_materialization("reading_plan_edit")


@pytest.mark.asyncio
async def test_3470_missing_volume_identity_unresolved_not_guessed(
    async_db: AsyncSession,
) -> None:
    """Unmatched/missing volume identity stays unresolved; no guessing (#3470 #3)."""
    assert CBL_SOURCE_ORDER_DEPENDENCY_MATERIALIZATION_BLOCKED is True


@pytest.mark.asyncio
async def test_3470_cross_volume_forever_people_not_collapsed(
    async_db: AsyncSession,
) -> None:
    """Distinct 1971/1988 Forever People threads are not collapsed.

    Two threads share one ComicVine issue identity, but only the thread
    whose series mapping matches the CBL entry is retained as a candidate.
    """
    from datetime import UTC, datetime

    from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
    from app.models.external_identity import (
        ExternalIdentity,
        ThreadExternalSeriesMapping,
    )
    from tests.conftest import get_or_create_user_async
    from tests.test_series_thread_reattach import _thread_with_numbers

    user = await get_or_create_user_async(async_db)

    thread_1971, issues_1971 = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="The Forever People (1971)",
        numbers=["1"],
        queue_position=1,
    )
    thread_1988, issues_1988 = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="Forever People (1988)",
        numbers=["1"],
        queue_position=2,
    )

    shared_issue_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="fp-shared-issue",
        metadata_json={"cover_date": "1988-01-01", "volume_id": "15796"},
    )
    series_1971 = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12987",
        metadata_json={},
    )
    series_1988 = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="15796",
        metadata_json={},
    )
    async_db.add_all([shared_issue_identity, series_1971, series_1988])
    await async_db.flush()

    from tests.test_cbl_source_identity_resolution import _map_issue
    await _map_issue(async_db, issue=issues_1971[0], identity=shared_issue_identity)
    await _map_issue(async_db, issue=issues_1988[0], identity=shared_issue_identity)

    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread_1971.id,
            external_identity_id=series_1971.id,
            status="confirmed",
            evidence_source="test",
            confidence=1.0,
        )
    )
    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread_1988.id,
            external_identity_id=series_1988.id,
            status="confirmed",
            evidence_source="test",
            confidence=1.0,
        )
    )
    await async_db.flush()

    source = CBLSource(
        repository="test/cbl-3470-forever",
        revision_sha="b" * 40,
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path="DC/Characters/unsorted/New Gods/The New Gods 001.cbl",
        name="Fourth World",
        declared_issue_count=1,
        content_hash="a" * 64,
        revision_sha="b" * 40,
        active=True,
    )
    async_db.add(source_list)
    await async_db.flush()
    async_db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=88,
            series_name="Forever People",
            issue_number="1",
            external_issue_identity_id=shared_issue_identity.id,
            external_series_identity_id=series_1988.id,
        )
    )
    await async_db.flush()

    from app.services.cbl_source_identity_resolution import (
        report_cbl_source_identity_resolution,
    )
    rows = await report_cbl_source_identity_resolution(
        async_db, user_id=user.id, source_list_id=source_list.id
    )
    assert len(rows) == 1
    assert rows[0].status in {"unique_confirmed_identity", "resolved_comicvine_volume"}
    assert rows[0].chosen_issue_id == issues_1988[0].id
    assert rows[0].chosen_issue_id != issues_1971[0].id
    candidate_issue_ids = {candidate.issue_id for candidate in rows[0].candidates}
    assert issues_1988[0].id in candidate_issue_ids
    assert issues_1971[0].id not in candidate_issue_ids


@pytest.mark.asyncio
async def test_3470_missing_volume_thread_identity_unresolved_not_guessed(
    async_db: AsyncSession,
) -> None:
    """No matching thread series mapping leaves the entry unresolved."""
    from datetime import UTC, datetime

    from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
    from app.models.external_identity import (
        ExternalIdentity,
    )
    from tests.conftest import get_or_create_user_async
    from tests.test_series_thread_reattach import _thread_with_numbers

    user = await get_or_create_user_async(async_db)
    thread_a, issues_a = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="The Forever People (1971)",
        numbers=["1"],
        queue_position=1,
    )
    thread_b, issues_b = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="Forever People (1988)",
        numbers=["1"],
        queue_position=2,
    )

    shared_issue_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="fp-missing-volume",
        metadata_json={},
    )
    async_db.add(shared_issue_identity)
    await async_db.flush()

    from tests.test_cbl_source_identity_resolution import _map_issue
    await _map_issue(async_db, issue=issues_a[0], identity=shared_issue_identity)
    await _map_issue(async_db, issue=issues_b[0], identity=shared_issue_identity)

    nonexistent_series = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="999999",
        metadata_json={},
    )
    async_db.add(nonexistent_series)
    await async_db.flush()

    source = CBLSource(
        repository="test/cbl-3470-missing-volume",
        revision_sha="b" * 40,
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path="DC/Characters/unsorted/New Gods/The New Gods 001.cbl",
        name="Fourth World",
        declared_issue_count=1,
        content_hash="a" * 64,
        revision_sha="b" * 40,
        active=True,
    )
    async_db.add(source_list)
    await async_db.flush()
    async_db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=1,
            series_name="Forever People",
            issue_number="1",
            external_issue_identity_id=shared_issue_identity.id,
            external_series_identity_id=nonexistent_series.id,
        )
    )
    await async_db.flush()

    from app.services.cbl_source_identity_resolution import (
        report_cbl_source_identity_resolution,
    )
    rows = await report_cbl_source_identity_resolution(
        async_db, user_id=user.id, source_list_id=source_list.id
    )
    assert len(rows) == 1
    assert rows[0].status == "unmatched"
    assert rows[0].chosen_issue_id is None


@pytest.mark.asyncio
async def test_3470_multiple_candidates_without_exact_volume_unmatched(
    async_db: AsyncSession,
) -> None:
    """Multiple confirmed matches without an exact volume match stay unmatched.

    Each rejected candidate is reported with its own series identity (or
    "unknown"), never the CBL issue's volume_id repeated for every candidate,
    and a missing CBL volume identity never renders as the literal "None".
    """
    from datetime import UTC, datetime

    from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
    from app.models.external_identity import (
        ExternalIdentity,
        ThreadExternalSeriesMapping,
    )
    from tests.conftest import get_or_create_user_async
    from tests.test_series_thread_reattach import _thread_with_numbers

    user = await get_or_create_user_async(async_db)
    thread_a, issues_a = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="The Forever People (1971)",
        numbers=["1"],
        queue_position=1,
    )
    thread_b, issues_b = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="Forever People (1988)",
        numbers=["1"],
        queue_position=2,
    )

    shared_issue_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="fp-multi-no-volume",
        metadata_json={"cover_date": "1988-01-01", "volume_id": "15796"},
    )
    series_a = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12987",
        metadata_json={},
    )
    series_b = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="15797",
        metadata_json={},
    )
    async_db.add_all([shared_issue_identity, series_a, series_b])
    await async_db.flush()

    from tests.test_cbl_source_identity_resolution import _map_issue
    await _map_issue(async_db, issue=issues_a[0], identity=shared_issue_identity)
    await _map_issue(async_db, issue=issues_b[0], identity=shared_issue_identity)

    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread_a.id,
            external_identity_id=series_a.id,
            status="confirmed",
            evidence_source="test",
            confidence=1.0,
        )
    )
    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread_b.id,
            external_identity_id=series_b.id,
            status="confirmed",
            evidence_source="test",
            confidence=1.0,
        )
    )
    await async_db.flush()

    source = CBLSource(
        repository="test/cbl-3470-multi-no-volume",
        revision_sha="b" * 40,
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path="DC/Characters/unsorted/New Gods/The New Gods 001.cbl",
        name="Fourth World",
        declared_issue_count=1,
        content_hash="a" * 64,
        revision_sha="b" * 40,
        active=True,
    )
    async_db.add(source_list)
    await async_db.flush()
    async_db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=1,
            series_name="Forever People",
            issue_number="1",
            external_issue_identity_id=shared_issue_identity.id,
            external_series_identity_id=None,
        )
    )
    await async_db.flush()

    from app.services.cbl_source_identity_resolution import (
        report_cbl_source_identity_resolution,
    )
    rows = await report_cbl_source_identity_resolution(
        async_db, user_id=user.id, source_list_id=source_list.id
    )
    assert len(rows) == 1
    assert rows[0].status == "unmatched"
    assert rows[0].chosen_issue_id is None
    candidate_series = {candidate.series_external_id for candidate in rows[0].candidates}
    assert candidate_series == {"12987", "15797"}
    assert len(rows[0].candidates) == 2
    # The CBL issue's volume_id must not be repeated as each candidate's volume.
    assert "15796" not in rows[0].evidence
    # Each candidate reports its own known series.
    assert "series 12987" in rows[0].evidence
    assert "series 15797" in rows[0].evidence
    # A missing CBL volume identity must never render as the literal "None".
    assert "volume None" not in rows[0].evidence
    assert "volume unknown" in rows[0].evidence
