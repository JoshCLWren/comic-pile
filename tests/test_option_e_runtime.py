"""Real PostgreSQL evidence that every offer uses one guarded Option E authority."""

from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import ReadingExecutionSettings, get_reading_execution_settings
from app.models import Dependency, Event, Issue, ReadingSession, Thread, User
from app.models.collection_exclusion import CollectionExclusion
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList, CustomCBLOverlapDecision
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.services.reading_eligibility_service import get_execution_eligibility
from app.services.thread_service import list_queue_threads
from comic_pile.queue import get_bounded_roll_pool_rows
from tests.conftest import get_or_create_user_async


@pytest.fixture
def option_e(monkeypatch: pytest.MonkeyPatch, default_user: User) -> Iterator[None]:
    """Enable only the test process with an explicitly non-production reference."""
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv("OPTION_E_APPROVED_PREVIEW", "local-test-fixture-no-production-approval")
    get_reading_execution_settings.cache_clear()
    try:
        yield
    finally:
        get_reading_execution_settings.cache_clear()


async def _series(
    db: AsyncSession,
    owner_id: int,
    title: str,
    position: int,
    *,
    count: int = 2,
    status: str = "active",
    blocked: bool = False,
) -> tuple[Thread, list[Issue]]:
    """Seed natural issue order independently of deliberately stale cache fields."""
    thread = Thread(
        user_id=owner_id,
        title=title,
        format="Comic",
        queue_position=position,
        status=status,
        is_blocked=blocked,
        total_issues=count,
        issues_remaining=count,
    )
    db.add(thread)
    await db.flush()
    issues = [
        Issue(thread_id=thread.id, issue_number=str(i), position=i, status="unread")
        for i in range(1, count + 1)
    ]
    db.add_all(issues)
    await db.flush()
    if issues:
        thread.next_unread_issue_id = issues[0].id
    await db.flush()
    return thread, issues


async def test_loose_independence_and_typed_prerequisite_with_legacy_looking_note(
    option_e: None,
    async_db: AsyncSession,
) -> None:
    """Reader provenance wins over note spelling; loose adjacency adds no blocker."""
    user = await get_or_create_user_async(async_db)
    one, issues_one = await _series(async_db, user.id, "One", 1)
    two, issues_two = await _series(async_db, user.id, "Two", 2)
    reading_list = CustomCBLList(user_id=user.id, name="Loose", mode="loose")
    async_db.add(reading_list)
    await async_db.flush()
    async_db.add_all(
        [
            CustomCBLEntry(list_id=reading_list.id, issue_id=issues_one[0].id, position=1),
            CustomCBLEntry(list_id=reading_list.id, issue_id=issues_two[0].id, position=2),
        ]
    )
    await async_db.flush()
    live = await get_execution_eligibility(async_db, user.id)
    assert live is not None and live.candidate_ids() == {one.id, two.id}
    async_db.add(
        Dependency(
            source_issue_id=issues_one[0].id,
            target_issue_id=issues_two[0].id,
            origin="reader",
            note="cbl-order:this is reader prose, not a generated edge",
        )
    )
    await async_db.flush()
    updated = await get_execution_eligibility(async_db, user.id)
    assert updated is not None and updated.candidate_ids() == {one.id}
    assert updated.threads[two.id].blockers[0].origin == "reader"
    assert updated.threads[two.id].blockers[0].waiting_on_issue_ids == (issues_one[0].id,)
    from app.repositories.reading_shadow_repository import load_shadow_inputs
    from app.services.reading_shadow_service import compare_reading_eligibility

    report = compare_reading_eligibility(await load_shadow_inputs(async_db, user.id))
    rows = report["threads"]
    assert isinstance(rows, list)
    target = next(row for row in rows if isinstance(row, dict) and row["thread_id"] == two.id)
    assert target["legacy_stored_frontier_blocked"] is False
    assert target["proposed_eligible"] is False


async def test_snapshot_shared_until_relevant_write_and_disabled_mode_is_inert(
    option_e: None,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session bookkeeping shares an answer; issue writes invalidate it safely."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _series(async_db, user.id, "Single", 1, count=1)
    first = await get_execution_eligibility(async_db, user.id)
    async_db.add(ReadingSession(user_id=user.id))
    await async_db.flush()
    assert await get_execution_eligibility(async_db, user.id) is first
    issues[0].status = "read"
    await async_db.flush()
    second = await get_execution_eligibility(async_db, user.id)
    assert second is not first and second is not None and not second.candidate_ids()
    assert thread.is_blocked is False
    monkeypatch.setenv("OPTION_E_ENABLED", "false")
    get_reading_execution_settings.cache_clear()
    assert await get_execution_eligibility(async_db, user.id) is None


async def test_overlap_decision_write_invalidates_the_shared_snapshot(
    option_e: None,
    async_db: AsyncSession,
) -> None:
    """A same-transaction overlap decision reloads eligibility instead of going stale.

    A saved ``CustomCBLOverlapDecision`` changes strict-order blockers, so an
    in-transaction write must discard the cached Option E answer exactly like an
    Issue or Dependency write, before any commit happens.
    """
    user = await get_or_create_user_async(async_db)
    waiting_thread, waiting_issues = await _series(async_db, user.id, "Waiting", 1, count=1)
    continuing_thread, continuing_issues = await _series(
        async_db, user.id, "Continuing", 2, count=1
    )
    waiting_identity = ExternalIdentity(
        provider="comicvine", entity_type="series", external_id="9001"
    )
    continuing_identity = ExternalIdentity(
        provider="comicvine", entity_type="series", external_id="9002"
    )
    async_db.add_all([waiting_identity, continuing_identity])
    await async_db.flush()
    async_db.add_all(
        [
            ThreadExternalSeriesMapping(
                thread_id=waiting_thread.id,
                external_identity_id=waiting_identity.id,
                status="confirmed",
                evidence_source="test",
            ),
            ThreadExternalSeriesMapping(
                thread_id=continuing_thread.id,
                external_identity_id=continuing_identity.id,
                status="confirmed",
                evidence_source="test",
            ),
        ]
    )
    reading_list = CustomCBLList(user_id=user.id, name="Order", mode="strict")
    async_db.add(reading_list)
    await async_db.flush()
    async_db.add_all(
        [
            CustomCBLEntry(list_id=reading_list.id, issue_id=waiting_issues[0].id, position=1),
            CustomCBLEntry(list_id=reading_list.id, issue_id=continuing_issues[0].id, position=2),
        ]
    )
    await async_db.flush()
    shared = await get_execution_eligibility(async_db, user.id)
    assert shared is not None
    assert shared.threads[waiting_thread.id].eligible
    blocked = shared.threads[continuing_thread.id]
    assert not blocked.eligible
    assert blocked.blockers[0].waiting_on_issue_ids == (waiting_issues[0].id,)

    async_db.add(
        CustomCBLOverlapDecision(
            user_id=user.id,
            list_id=reading_list.id,
            continuing_external_identity_id=continuing_identity.id,
            waiting_external_identity_id=waiting_identity.id,
        )
    )
    await async_db.flush()

    reloaded = await get_execution_eligibility(async_db, user.id)
    assert reloaded is not None
    assert reloaded is not shared
    assert reloaded.threads[continuing_thread.id].eligible


def test_activation_requires_a_separate_approval_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deploying code cannot activate execution with an empty approval reference."""
    monkeypatch.delenv("OPTION_E_APPROVED_PREVIEW", raising=False)
    assert ReadingExecutionSettings(enabled=False).enabled is False
    with pytest.raises(ValidationError, match="owner-approved"):
        ReadingExecutionSettings(enabled=True, approved_preview=" ")


async def test_old_dependencies_do_not_override_canonical_reading_intent(
    option_e: None,
    async_db: AsyncSession,
) -> None:
    """Legacy and compiled edges remain audit data, not hidden reading-order rules."""
    user = await get_or_create_user_async(async_db)
    first, a = await _series(async_db, user.id, "Historical source", 1)
    legacy, b = await _series(async_db, user.id, "Old checkpoint", 2)
    compiled, c = await _series(async_db, user.id, "Generated copy", 3)
    deliberate, d = await _series(async_db, user.id, "Explicit exception", 4)
    async_db.add_all(
        [
            Dependency(
                source_issue_id=a[0].id, target_issue_id=b[0].id, note="Old reading plan checkpoint"
            ),
            Dependency(
                source_issue_id=a[0].id,
                target_issue_id=c[0].id,
                origin="converted",
                classification="C",
                provenance="legacy continuity-rule expansion",
            ),
            Dependency(
                source_issue_id=a[0].id,
                target_issue_id=d[0].id,
                origin="reader",
                classification="A",
                provenance="Explicit reader requirement",
            ),
        ]
    )
    await async_db.flush()
    live = await get_execution_eligibility(async_db, user.id)
    assert live is not None
    assert live.candidate_ids() == {first.id, legacy.id, compiled.id}
    assert not live.threads[deliberate.id].eligible
    assert live.threads[deliberate.id].blockers[0].origin == "reader"
    from app.repositories.reading_shadow_repository import load_shadow_inputs
    from app.services.reading_shadow_service import compare_reading_eligibility

    shadow = compare_reading_eligibility(await load_shadow_inputs(async_db, user.id))
    rows = shadow["threads"]
    assert isinstance(rows, list)
    assert all(isinstance(row, dict) for row in rows)
    by_thread = {row["thread_id"]: row for row in rows if isinstance(row, dict)}
    assert by_thread[legacy.id]["legacy_derived_frontier_blocked"] is True
    assert by_thread[legacy.id]["proposed_eligible"] is True
    assert by_thread[compiled.id]["proposed_eligible"] is True
    assert by_thread[deliberate.id]["proposed_eligible"] is False
    summary = shadow["summary"]
    assert isinstance(summary, dict)
    inert_count = summary["inert_dependencies"]
    assert isinstance(inert_count, int) and inert_count >= 2


async def test_v2_identity_fanout_does_not_shrink_thread_die_pool(
    option_e: None,
    async_db: AsyncSession,
) -> None:
    """Multiple stored mappings must not consume another eligible Thread's slot."""
    from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping

    user = await get_or_create_user_async(async_db)
    one, issues = await _series(async_db, user.id, "Multiple identities", 1)
    two, _ = await _series(async_db, user.id, "Other series", 2)
    for external_id in ["4000-111", "4000-222"]:
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id=external_id,
            metadata_json={"issue_number": "1", "volume_id": 123, "volume_name": "Identity"},
        )
        async_db.add(identity)
        await async_db.flush()
        async_db.add(
            IssueExternalIdentityMapping(
                issue_id=issues[0].id,
                external_identity_id=identity.id,
                status="candidate",
            )
        )
    await async_db.flush()
    live = await get_execution_eligibility(async_db, user.id)
    assert live is not None
    assert live.candidate_ids() == {one.id, two.id}


@pytest.mark.parametrize("stored_id,excluded_id", [("4050-123", "123"), ("123", "4050-123")])
async def test_volume_exclusions_use_stable_normalized_identity(
    option_e: None,
    async_db: AsyncSession,
    stored_id: str,
    excluded_id: str,
) -> None:
    """Equivalent ComicVine ID spellings cannot resurrect an excluded volume."""
    from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping

    user = await get_or_create_user_async(async_db)
    thread, _ = await _series(async_db, user.id, "Excluded by identity", 1)
    identity = ExternalIdentity(provider="comicvine", entity_type="series", external_id=stored_id)
    async_db.add(identity)
    await async_db.flush()
    async_db.add_all(
        [
            ThreadExternalSeriesMapping(
                thread_id=thread.id,
                external_identity_id=identity.id,
                status="confirmed",
            ),
            CollectionExclusion(
                user_id=user.id, provider="comicvine", external_volume_id=excluded_id
            ),
        ]
    )
    await async_db.flush()
    live = await get_execution_eligibility(async_db, user.id)
    assert live is not None and not live.candidate_ids()
    assert live.threads[thread.id].next_issue_id is None


def test_queue_cursor_cannot_cross_execution_modes() -> None:
    """Activation cannot silently reinterpret a cursor's blocked-group ordering."""
    from app.services.queue_pagination import QueueCursor, decode_queue_cursor, encode_queue_cursor

    token = encode_queue_cursor(QueueCursor(sort="position", search="", values=("0", "1", "7")))
    with pytest.raises(ValueError, match="Queue ordering changed"):
        decode_queue_cursor(token, sort="position", search="", execution="option_e")


async def test_activation_is_app_wide_with_reader_data_isolation(
    option_e: None,
    async_db: AsyncSession,
) -> None:
    """Every reader uses the canonical engine, but only their owned constraints."""
    first = await get_or_create_user_async(async_db)
    other = User(username="other_canonical_reader", password_hash="unused")
    async_db.add(other)
    await async_db.flush()
    one, one_issues = await _series(async_db, first.id, "First reader", 1)
    two, two_issues = await _series(async_db, other.id, "Second reader", 2)
    own_list = CustomCBLList(user_id=first.id, name="Private strict", mode="strict")
    async_db.add(own_list)
    await async_db.flush()
    async_db.add(CustomCBLEntry(list_id=own_list.id, issue_id=one_issues[1].id, position=1))
    await async_db.flush()
    first_result = await get_execution_eligibility(async_db, first.id)
    other_result = await get_execution_eligibility(async_db, other.id)
    assert first_result is not None and other_result is not None
    assert one.id in first_result.candidate_ids()
    assert two.id in other_result.candidate_ids()
    assert two.id not in first_result.threads
    assert one.id not in other_result.threads
    assert two_issues[0].id == other_result.threads[two.id].next_issue_id


async def test_empty_and_fully_excluded_queues_have_valid_live_sort_sql(
    option_e: None,
    async_db: AsyncSession,
) -> None:
    """No eligible IDs must not become a bare Boolean ORDER BY constant."""
    user = await get_or_create_user_async(async_db)
    empty = await list_queue_threads(
        async_db, user.id, search=None, sort="position", page_size=50, page_token=None
    )
    assert empty.threads == []
    thread, _ = await _series(async_db, user.id, "Entirely excluded", 1)
    async_db.add(CollectionExclusion(user_id=user.id, thread_id=thread.id))
    await async_db.commit()
    excluded = await list_queue_threads(
        async_db, user.id, search=None, sort="position", page_size=50, page_token=None
    )
    assert len(excluded.threads) == 1
    assert excluded.threads[0].is_blocked is True




async def test_option_e_roll_pool_never_reaggregates_unread_issues(
    option_e: None,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Canonical pool uses the snapshot's counts/frontiers without an Issue SQL join."""
    user = await get_or_create_user_async(async_db)
    waiting, waiting_issues = await _series(async_db, user.id, "Waiting", 2)
    ahead, ahead_issues = await _series(async_db, user.id, "Ahead", 1, blocked=True)
    snoozed, _ = await _series(async_db, user.id, "Snoozed", 3)
    async_db.add(CollectionExclusion(user_id=user.id, issue_id=waiting_issues[0].id))
    await async_db.flush()
    # Deliberately stale saved counters and flags must not determine the offer.
    ahead.issues_remaining = 0
    ahead.is_blocked = True
    waiting.next_unread_issue_id = waiting_issues[0].id
    await async_db.commit()

    snapshot = await get_execution_eligibility(async_db, user.id)
    assert snapshot is not None
    assert snapshot.threads[waiting.id].next_issue_id == waiting_issues[1].id
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", capture)
    try:
        pool = await get_bounded_roll_pool_rows(user.id, async_db, 10, snoozed_ids=[snoozed.id])
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", capture)

    assert [(row.id, count, number) for row, count, number in pool] == [
        (ahead.id, 2, ahead_issues[0].issue_number),
        (waiting.id, 1, waiting_issues[1].issue_number),
    ]
    assert len(statements) == 1
    sql = statements[0].lower()
    assert "from threads" in sql
    assert "join issues" not in sql
    assert "from issues" not in sql
    assert "count(" not in sql


