"""Real PostgreSQL evidence that every offer uses one guarded Option E authority."""

from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import ReadingExecutionSettings, get_reading_execution_settings
from app.models import Dependency, Event, Issue, ReadingSession, Snapshot, Thread, User
from app.models.collection_exclusion import CollectionExclusion
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList, CustomCBLOverlapDecision
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.services.reading_eligibility_service import get_execution_eligibility
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
    async_db.add_all([
        Dependency(source_issue_id=a[0].id, target_issue_id=b[0].id,
                   note="Old reading plan checkpoint"),
        Dependency(source_issue_id=a[0].id, target_issue_id=c[0].id,
                   origin="converted", classification="C",
                   provenance="legacy continuity-rule expansion"),
        Dependency(source_issue_id=a[0].id, target_issue_id=d[0].id,
                   origin="reader", classification="A",
                   provenance="Explicit reader requirement"),
    ])
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
    from app.services.roll_v2_projection import get_v2_rollable_projection

    user = await get_or_create_user_async(async_db)
    one, issues = await _series(async_db, user.id, "Multiple identities", 1)
    two, _ = await _series(async_db, user.id, "Other series", 2)
    session = ReadingSession(user_id=user.id)
    async_db.add(session)
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
    items, _, _ = await get_v2_rollable_projection(
        async_db,
        user_id=user.id,
        die_size=2,
        excluded_thread_ids=[],
        session_id=session.id,
    )
    assert [item.thread.id for item in items] == [one.id, two.id]


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
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """No eligible IDs must not become a bare Boolean ORDER BY constant."""
    empty = await auth_client.get("/api/v1/threads/", params={"sort": "position"})
    assert empty.status_code == 200 and empty.json()["threads"] == []
    user = await get_or_create_user_async(async_db)
    thread, _ = await _series(async_db, user.id, "Entirely excluded", 1)
    async_db.add(CollectionExclusion(user_id=user.id, thread_id=thread.id))
    await async_db.commit()
    excluded = await auth_client.get("/api/v1/threads/", params={"sort": "position"})
    assert excluded.status_code == 200
    assert len(excluded.json()["threads"]) == 1
    assert excluded.json()["threads"][0]["is_blocked"] is True


async def test_exclusion_delete_rolls_back_when_stored_graph_is_invalid(
    option_e: None,
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Exclusions cannot be used to hide stored cycles from write validation."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _series(async_db, user.id, "Natural order", 1)
    reading_list = CustomCBLList(user_id=user.id, name="Backwards", mode="strict")
    exclusion = CollectionExclusion(user_id=user.id, thread_id=thread.id)
    async_db.add_all([reading_list, exclusion])
    await async_db.flush()
    async_db.add_all(
        [
            CustomCBLEntry(list_id=reading_list.id, issue_id=issues[1].id, position=1),
            CustomCBLEntry(list_id=reading_list.id, issue_id=issues[0].id, position=2),
        ]
    )
    exclusion_id = exclusion.id
    await async_db.commit()
    response = await auth_client.delete(f"/api/v1/collection-exclusions/{exclusion_id}")
    assert response.status_code == 422
    assert "cycle" in response.json()["detail"].casefold()
    assert await async_db.get(CollectionExclusion, exclusion_id) is not None


async def test_rating_a_stale_offer_cannot_consume_the_next_issue(
    option_e: None,
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A read elsewhere invalidates the offer instead of moving its rating forward."""
    user = await get_or_create_user_async(async_db)
    _, issues = await _series(async_db, user.id, "Changed after roll", 1, count=3)
    issue_ids = [issue.id for issue in issues]
    await async_db.commit()
    offered = await auth_client.post("/api/v1/roll/")
    assert offered.status_code == 200 and offered.json()["issue_id"] == issue_ids[0]
    issue = await async_db.get(Issue, issue_ids[0])
    assert issue is not None
    issue.status = "read"
    await async_db.commit()
    response = await auth_client.post("/api/v1/rate/", json={"rating": 4.0})
    assert response.status_code == 409
    remaining = list(
        (await async_db.scalars(select(Issue.status).where(Issue.id.in_(issue_ids[1:])))).all()
    )
    assert remaining == ["unread", "unread"]
    assert await async_db.scalar(select(Event.id).where(Event.type == "rate")) is None


async def test_unidentified_legacy_offer_cannot_trigger_automatic_issue_migration(
    option_e: None,
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Missing canonical offer identity requires a new roll, never inferred read history."""
    from sqlalchemy import func

    user = await get_or_create_user_async(async_db)
    thread, _ = await _series(async_db, user.id, "Unidentified offer", 1)
    thread.total_issues = None
    thread.issues_remaining = 17
    reading_session = ReadingSession(user_id=user.id, pending_thread_id=thread.id)
    async_db.add(reading_session)
    await async_db.flush()
    async_db.add(
        Event(
            type="roll",
            session_id=reading_session.id,
            selected_thread_id=thread.id,
            issue_id=None,
            die=6,
            result=1,
        )
    )
    thread_id = thread.id
    await async_db.commit()
    response = await auth_client.post("/api/v1/rate/", json={"rating": 4.0, "issue_number": "9"})
    assert response.status_code == 409
    assert (
        await async_db.scalar(select(func.count(Issue.id)).where(Issue.thread_id == thread_id)) == 2
    )
    assert await async_db.scalar(select(Thread.total_issues).where(Thread.id == thread_id)) is None
    assert (
        await async_db.scalar(select(Thread.issues_remaining).where(Thread.id == thread_id)) == 17
    )


async def test_rating_rejects_an_offer_removed_from_the_queue(
    option_e: None,
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A pending offer cannot bypass current queue membership at rating time."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _series(async_db, user.id, "Removed after roll", 1)
    thread_id, issue_id = thread.id, issues[0].id
    await async_db.commit()
    offered = await auth_client.post("/api/v1/roll/")
    assert offered.status_code == 200 and offered.json()["issue_id"] == issue_id
    current = await async_db.get(Thread, thread_id)
    assert current is not None
    current.queue_position = 0
    await async_db.commit()
    response = await auth_client.post("/api/v1/rate/", json={"rating": 4.0})
    assert response.status_code == 409
    assert await async_db.scalar(select(Issue.status).where(Issue.id == issue_id)) == "unread"
    assert await async_db.scalar(select(Event.id).where(Event.type == "rate")) is None


async def test_live_explanations_agree_for_all_reader_surfaces(
    option_e: None, auth_client: AsyncClient, async_db: AsyncSession,
) -> None:
    """Strict list and stable prerequisite both survive stale legacy flags."""
    user = await get_or_create_user_async(async_db)
    first, first_issues = await _series(async_db, user.id, "The Dead Remembered", 1)
    later, later_issues = await _series(async_db, user.id, "King of Fear", 2)
    prerequisite, prerequisite_issues = await _series(async_db, user.id, "Required special", 3)
    reading_list = CustomCBLList(user_id=user.id, name="Julix", mode="strict")
    async_db.add(reading_list)
    await async_db.flush()
    async_db.add_all([
        CustomCBLEntry(list_id=reading_list.id, issue_id=first_issues[0].id, position=1),
        CustomCBLEntry(list_id=reading_list.id, issue_id=later_issues[0].id, position=2),
        CustomCBLEntry(list_id=reading_list.id, issue_id=later_issues[1].id, position=3, skipped=True),
        Dependency(source_issue_id=prerequisite_issues[0].id, target_issue_id=later_issues[0].id,
                   origin="reader"),
    ])
    later.next_unread_issue_id = later_issues[1].id
    list_id, first_id, later_id = reading_list.id, first.id, later.id
    first_issue_id, later_issue_id = first_issues[0].id, later_issues[0].id
    source_issue_id = prerequisite_issues[0].id
    await async_db.commit()

    batch = await auth_client.post("/api/v1/threads:getBlockingInfo", json={"thread_ids": [later_id]})
    assert batch.status_code == 200
    explanation = batch.json()["threads"][str(later_id)]
    assert explanation["is_blocked"] is True
    assert {row["issue_id"] for row in explanation["blocking_dependencies"]} == {
        first_issue_id, source_issue_id,
    }
    assert any("Strict order in Julix" in reason for reason in explanation["blocking_reasons"])
    assert any("Reader prerequisite" in reason for reason in explanation["blocking_reasons"])

    single = await auth_client.post(f"/api/v1/threads/{later_id}:getBlockingInfo")
    assert single.json() == explanation
    detail = await auth_client.get(f"/api/v1/threads/{later_id}")
    assert detail.status_code == 200
    assert detail.json()["next_unread_issue_id"] == later_issue_id
    assert detail.json()["blocking_reasons"] == explanation["blocking_reasons"]
    page = await auth_client.get("/api/v1/threads/", params={"page_size": 50})
    queue_row = next(row for row in page.json()["threads"] if row["id"] == later_id)
    assert queue_row["blocking_reasons"] == explanation["blocking_reasons"]

    reader = await auth_client.get(f"/api/v1/custom-cbls/{list_id}/reader")
    assert reader.status_code == 200
    view = reader.json()
    assert view["execution_mode"] == "option_e"
    assert len(view["entries"]) == 3
    assert view["entries"][0]["availability"] == "available"
    assert view["entries"][1]["availability"] == "blocked"
    assert view["entries"][1]["explanation"] == explanation
    assert view["entries"][2]["skipped"] is True
    assert view["entries"][2]["availability"] == "later"
    plan_response = await auth_client.post("/api/v1/continuity-plans/", json={
        "name": "Historical shorter copy", "ordering_mode": "informational",
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [
            {"id": "first", "node_type": "issue", "ref_id": first_issue_id,
             "lane_id": "main", "position": 0},
            {"id": "later", "node_type": "issue", "ref_id": later_issue_id,
             "lane_id": "main", "position": 1},
        ],
    })
    assert plan_response.status_code == 201, plan_response.text
    plan_id = plan_response.json()["id"]
    plan_reader = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/reader")
    assert plan_reader.status_code == 200
    assert plan_reader.json()["execution_mode"] == "option_e"
    blocked = plan_reader.json()["blocked_next"]
    assert len(blocked) == 1
    assert blocked[0]["issue_id"] == later_issue_id
    assert [row["explanation"] for row in blocked[0]["blockers"]] == explanation["blocking_reasons"]
    # Reading explanations does not repair stored pointers or cached flags.
    await async_db.refresh(later)
    assert later.next_unread_issue_id != later_issue_id
    assert later.is_blocked is False
    first_detail = await auth_client.get(f"/api/v1/threads/{first_id}")
    assert first_detail.json()["is_blocked"] is False


async def test_reading_list_reader_is_inactive_until_approved(
    auth_client: AsyncClient, async_db: AsyncSession,
) -> None:
    """Opening the reader cannot turn saved strict intent into active execution."""
    user = await get_or_create_user_async(async_db)
    _, issues = await _series(async_db, user.id, "Ordinary", 1)
    reading_list = CustomCBLList(user_id=user.id, name="Inactive strict", mode="strict")
    async_db.add(reading_list)
    await async_db.flush()
    async_db.add(CustomCBLEntry(list_id=reading_list.id, issue_id=issues[0].id, position=1))
    list_id = reading_list.id
    await async_db.commit()
    response = await auth_client.get(f"/api/v1/custom-cbls/{list_id}/reader")
    assert response.status_code == 200
    assert response.json()["execution_mode"] == "legacy"
    assert response.json()["entries"][0]["availability"] == "legacy"
    assert response.json()["entries"][0]["explanation"] is None
    assert (await auth_client.get("/api/v1/custom-cbls/999999999/reader")).status_code == 404


async def test_list_reader_distinguishes_exclusions_inactive_and_empty_lists(
    option_e: None, auth_client: AsyncClient, async_db: AsyncSession,
) -> None:
    """Collection exclusions, inactivity and no membership never masquerade as blockers."""
    user = await get_or_create_user_async(async_db)
    _, excluded_issues = await _series(async_db, user.id, "Excluded", 1)
    _, inactive_issues = await _series(async_db, user.id, "Inactive", 2, status="paused")
    reading_list = CustomCBLList(user_id=user.id, name="States", mode="loose")
    empty = CustomCBLList(user_id=user.id, name="Empty", mode="loose")
    foreign_user = await get_or_create_user_async(async_db, username="other-list-reader")
    foreign = CustomCBLList(user_id=foreign_user.id, name="Private", mode="loose")
    async_db.add_all([reading_list, empty, foreign])
    await async_db.flush()
    async_db.add_all([
        CustomCBLEntry(list_id=reading_list.id, issue_id=excluded_issues[0].id, position=1),
        CustomCBLEntry(list_id=reading_list.id, issue_id=inactive_issues[0].id, position=2),
        CollectionExclusion(user_id=user.id, issue_id=excluded_issues[0].id),
    ])
    list_id, empty_id, foreign_id = reading_list.id, empty.id, foreign.id
    await async_db.commit()
    response = await auth_client.get(f"/api/v1/custom-cbls/{list_id}/reader")
    assert response.status_code == 200
    assert [entry["availability"] for entry in response.json()["entries"]] == ["excluded", "inactive"]
    empty_response = await auth_client.get(f"/api/v1/custom-cbls/{empty_id}/reader")
    assert empty_response.json()["entries"] == []
    assert (await auth_client.get(f"/api/v1/custom-cbls/{foreign_id}/reader")).status_code == 404


async def test_thread_connection_panel_uses_only_reader_prerequisites_when_enabled(
    option_e: None, auth_client: AsyncClient, async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Historical edges cannot contradict the live Thread availability explanation."""
    user = await get_or_create_user_async(async_db)
    historical, old = await _series(async_db, user.id, "Historical", 1)
    generated, compiled = await _series(async_db, user.id, "Generated", 2)
    deliberate, explicit = await _series(async_db, user.id, "Reader", 3)
    target, target_issues = await _series(async_db, user.id, "Target", 4)
    async_db.add_all([
        Dependency(source_issue_id=old[0].id, target_issue_id=target_issues[0].id),
        Dependency(source_issue_id=compiled[0].id, target_issue_id=target_issues[0].id,
                   origin="converted", classification="C", provenance="Old compiler"),
        Dependency(source_issue_id=explicit[0].id, target_issue_id=target_issues[0].id,
                   origin="reader"),
    ])
    historical_id, generated_id, reader_id, target_id = (
        historical.id, generated.id, deliberate.id, target.id,
    )
    await async_db.commit()
    response = await auth_client.get(f"/api/v1/threads/{target_id}/connected")
    assert response.status_code == 200
    assert {row["thread_id"] for row in response.json()["connected_threads"]} == {reader_id}
    outgoing = await auth_client.get(f"/api/v1/threads/{generated_id}/connected")
    assert outgoing.status_code == 200
    assert outgoing.json()["connected_threads"] == []

    monkeypatch.setenv("OPTION_E_ENABLED", "false")
    get_reading_execution_settings.cache_clear()
    legacy = await auth_client.get(f"/api/v1/threads/{target_id}/connected")
    assert legacy.status_code == 200
    assert {row["thread_id"] for row in legacy.json()["connected_threads"]} == {
        historical_id, generated_id, reader_id,
    }


@pytest.mark.parametrize("stale_cache", [False, True])
async def test_read_now_binds_canonical_issue_for_rating_and_undo(
    option_e: None,
    auth_client: AsyncClient,
    async_db: AsyncSession,
    stale_cache: bool,
) -> None:
    """Read now must persist the same exact offer that rating consumes."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _series(async_db, user.id, "Read now regression", 1)
    thread_id, issue_ids = thread.id, [issue.id for issue in issues]
    if stale_cache:
        thread.is_blocked = True
        thread.issues_remaining = 0
        thread.total_issues = None
        thread.next_unread_issue_id = issue_ids[1]
    session = ReadingSession(user_id=user.id, pending_issue_id=issue_ids[1])
    async_db.add(session)
    await async_db.flush()
    session_id = session.id
    await async_db.commit()

    selected = await auth_client.post(f"/api/v1/threads/{thread_id}/set-pending")
    assert selected.status_code == 200, selected.text
    assert selected.json()["issue_id"] == issue_ids[0]
    assert selected.json()["issues_remaining"] == 2
    event = await async_db.scalar(select(Event).where(Event.selection_method == "manual"))
    assert event is not None
    assert (event.selected_thread_id, event.issue_id, event.issue_number) == (
        thread_id,
        issue_ids[0],
        "1",
    )
    assert (
        await async_db.scalar(
            select(ReadingSession.pending_issue_id).where(ReadingSession.id == session_id)
        )
        == issue_ids[0]
    )

    rated = await auth_client.post("/api/v1/rate/", json={"rating": 4.0})
    assert rated.status_code == 200, rated.text
    assert rated.json()["roll_reconciliation"]["last_read"]["issue_id"] == issue_ids[0]
    assert await async_db.scalar(select(Issue.status).where(Issue.id == issue_ids[0])) == "read"
    assert await async_db.scalar(select(Issue.status).where(Issue.id == issue_ids[1])) == "unread"
    snapshot_id = await async_db.scalar(
        select(Snapshot.id)
        .where(
            Snapshot.session_id == session_id,
            Snapshot.description == "After rating",
        )
        .order_by(Snapshot.id.desc())
        .limit(1)
    )
    assert snapshot_id is not None
    undone = await auth_client.post(f"/api/v1/undo/{session_id}/undo/{snapshot_id}")
    assert undone.status_code == 200, undone.text
    assert await async_db.scalar(select(Issue.status).where(Issue.id == issue_ids[0])) == "unread"


async def test_read_now_rejects_canonical_blocked_and_session_skipped_threads(
    option_e: None,
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Read now cannot offer an issue the rating guard would reject."""
    user = await get_or_create_user_async(async_db)
    first, first_issues = await _series(async_db, user.id, "Required first", 1)
    blocked, blocked_issues = await _series(async_db, user.id, "Wait for first", 2)
    reading_list = CustomCBLList(user_id=user.id, name="Read now order", mode="strict")
    async_db.add(reading_list)
    await async_db.flush()
    async_db.add_all(
        [
            CustomCBLEntry(list_id=reading_list.id, issue_id=first_issues[0].id, position=1),
            CustomCBLEntry(list_id=reading_list.id, issue_id=blocked_issues[0].id, position=2),
            ReadingSession(user_id=user.id, skipped_thread_ids=[first.id]),
        ]
    )
    thread_ids = [first.id, blocked.id]
    await async_db.commit()
    for thread_id in thread_ids:
        selected = await auth_client.post(f"/api/v1/threads/{thread_id}/set-pending")
        assert selected.status_code == 400, selected.text
    assert await async_db.scalar(select(Event.id).where(Event.selection_method == "manual")) is None


async def test_read_now_clears_current_snooze_before_rating(
    option_e: None,
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Manual selection keeps its explicit current-session unsnooze behavior."""
    from datetime import UTC, datetime, timedelta

    user = await get_or_create_user_async(async_db)
    thread, issues = await _series(async_db, user.id, "Read now snoozed", 1)
    session = ReadingSession(user_id=user.id, snoozed_thread_ids=[thread.id])
    async_db.add(session)
    await async_db.flush()
    async_db.add(Event(
        type="snooze", thread_id=thread.id, session_id=session.id,
        timestamp=datetime.now(UTC) - timedelta(minutes=1),
    ))
    thread_id, issue_id, session_id = thread.id, issues[0].id, session.id
    await async_db.commit()
    selected = await auth_client.post(f"/api/v1/threads/{thread_id}/set-pending")
    assert selected.status_code == 200, selected.text
    assert selected.json()["issue_id"] == issue_id
    assert await async_db.scalar(select(Event.id).where(Event.type == "unsnooze")) is not None
    assert await async_db.scalar(
        select(ReadingSession.snoozed_thread_ids).where(ReadingSession.id == session_id)
    ) == []
    rated = await auth_client.post("/api/v1/rate/", json={"rating": 4.0})
    assert rated.status_code == 200, rated.text
    assert rated.json()["roll_reconciliation"]["last_read"]["issue_id"] == issue_id


async def test_set_current_issue_creates_a_rateable_canonical_offer(
    option_e: None, auth_client: AsyncClient, async_db: AsyncSession,
) -> None:
    """Correcting the current issue also enters rating with a fresh bound offer."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _series(async_db, user.id, "Correct then rate", 1, count=3)
    thread.total_issues = None
    thread_id, issue_ids = thread.id, [issue.id for issue in issues]
    await async_db.commit()
    corrected = await auth_client.post(
        f"/api/v1/threads/{thread_id}:setCurrentIssue", json={"issue_number": "2"},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["issue_id"] == issue_ids[1]
    rated = await auth_client.post("/api/v1/rate/", json={"rating": 4.0})
    assert rated.status_code == 200, rated.text
    assert rated.json()["roll_reconciliation"]["last_read"]["issue_id"] == issue_ids[1]
    statuses = list((await async_db.scalars(
        select(Issue.status).where(Issue.id.in_(issue_ids)).order_by(Issue.position)
    )).all())
    assert statuses == ["read", "read", "unread"]


async def test_canonical_prerequisite_read_now_ignores_retired_frontier_and_edges(
    option_e: None, auth_client: AsyncClient, async_db: AsyncSession,
) -> None:
    """Recovery Read now selects and rates the canonical prerequisite leaf."""
    user = await get_or_create_user_async(async_db)
    source, source_issues = await _series(async_db, user.id, "Recovery first", 1, blocked=True)
    target, target_issues = await _series(async_db, user.id, "Recovery waiting", 2)
    source.next_unread_issue_id = source_issues[1].id
    _, historical_issues = await _series(async_db, user.id, "Retired blocker", 3)
    async_db.add(Dependency(
        source_issue_id=historical_issues[0].id, target_issue_id=source_issues[0].id,
        origin="converted", classification="C", provenance="Retired generated edge",
    ))
    reading_list = CustomCBLList(user_id=user.id, name="Recovery sequence", mode="strict")
    async_db.add(reading_list)
    await async_db.flush()
    async_db.add_all([
        CustomCBLEntry(list_id=reading_list.id, issue_id=source_issues[0].id, position=1),
        CustomCBLEntry(list_id=reading_list.id, issue_id=target_issues[0].id, position=2),
        ReadingSession(user_id=user.id, pending_thread_id=target.id, pending_issue_id=target_issues[0].id),
    ])
    source_id, target_id, issue_id = source.id, target.id, source_issues[0].id
    await async_db.commit()
    switched = await auth_client.post(
        "/api/v1/roll/switch-prerequisite", json={"node_type": "issue", "node_id": issue_id},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["original_thread_id"] == target_id
    assert switched.json()["target_thread_id"] == source_id
    assert switched.json()["target_issue_id"] == issue_id
    rated = await auth_client.post("/api/v1/rate/", json={"rating": 4.0})
    assert rated.status_code == 200, rated.text
    assert rated.json()["roll_reconciliation"]["last_read"]["issue_id"] == issue_id


async def test_rejected_current_issue_correction_does_not_commit_progress(
    option_e: None, async_db: AsyncSession,
) -> None:
    """Session initialization cannot commit progress before availability validation."""
    from app.services.errors import InvalidRequestError
    from app.services.thread_service import set_current_issue

    user = await get_or_create_user_async(async_db)
    _, source_issues = await _series(async_db, user.id, "Correction prerequisite", 1)
    target, target_issues = await _series(async_db, user.id, "Blocked correction", 2)
    async_db.add(Dependency(
        source_issue_id=source_issues[0].id, target_issue_id=target_issues[1].id,
        origin="reader", classification="A", provenance="Explicit correction prerequisite",
    ))
    owner_id, thread_id, issue_ids = user.id, target.id, [issue.id for issue in target_issues]
    await async_db.commit()
    with pytest.raises(InvalidRequestError):
        await set_current_issue(async_db, owner_id, thread_id, issue_number="2")
    await async_db.rollback()
    statuses = list((await async_db.scalars(
        select(Issue.status).where(Issue.id.in_(issue_ids)).order_by(Issue.position)
    )).all())
    assert statuses == ["unread", "unread"]
    assert await async_db.scalar(select(Event.id).where(Event.selection_method == "manual")) is None


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
    async_db.add(
        CollectionExclusion(user_id=user.id, issue_id=waiting_issues[0].id)
    )
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
        pool = await get_bounded_roll_pool_rows(
            user.id, async_db, 10, snoozed_ids=[snoozed.id]
        )
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



async def test_roll_response_reuses_precommit_snapshot_without_postcommit_reads(
    option_e: None,
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Successful Roll returns a dense Queue ordinal without a post-commit reload."""
    import logging
    import re

    from app.services.queue_display import display_positions

    user = await get_or_create_user_async(async_db)
    first, first_issues = await _series(async_db, user.id, "First", 3, count=1)
    second, second_issues = await _series(async_db, user.id, "Second", 19, count=1)
    async_db.add(
        ReadingSession(
            user_id=user.id,
            start_die=6,
            manual_die=6,
            active_bandwidth="balanced",
            bandwidth_source="manual",
            active_intent="balanced",
            intent_source="manual",
        )
    )
    await async_db.commit()

    did_commit = False
    after_commit_queries: list[str] = []

    def record_commit(session: object) -> None:
        nonlocal did_commit
        if session is async_db.sync_session:
            did_commit = True

    def record_query(
        conn: object, cursor: object, statement: str,
        parameters: object, context: object, executemany: bool,
    ) -> None:
        if did_commit:
            after_commit_queries.append(statement)

    event.listen(async_db.sync_session, "after_commit", record_commit)
    event.listen(db_engine.sync_engine, "before_cursor_execute", record_query)
    try:
        with caplog.at_level(logging.WARNING, logger="app.api.roll"):
            response = await auth_client.post("/api/v1/roll/")
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", record_query)
        event.remove(async_db.sync_session, "after_commit", record_commit)

    assert response.status_code == 200, response.text
    assert did_commit, "Roll must persist its selection before replying"
    assert after_commit_queries == [], (
        "A committed Roll must not launch a new transaction to hydrate the response: "
        f"{after_commit_queries}"
    )
    body = response.json()
    expected_issue_ids = {
        first.id: first_issues[0].id,
        second.id: second_issues[0].id,
    }
    assert body["issue_id"] == expected_issue_ids[body["thread_id"]]
    positions = await display_positions(async_db, user.id)
    assert body["queue_position"] == positions[body["thread_id"]]
    assert set(positions.values()) == {1, 2}

    summaries = [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.api.roll"
        and record.getMessage().startswith("roll.phase_timing")
    ]
    assert len(summaries) == 1
    stage = re.search(r"(?:^|,)response:[0-9.]+/[0-9.]+/([0-9]+)", summaries[0])
    assert stage is not None, summaries[0]
    assert int(stage.group(1)) <= 3, (
        "Response projection must not reload the multi-query Option E snapshot: "
        f"{summaries[0]}"
    )


async def test_roll_precommit_projection_does_not_ack_failed_commit(
    option_e: None,
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DTO built before commit is never returned when persistence fails."""
    user = await get_or_create_user_async(async_db)
    await _series(async_db, user.id, "Commit guard", 1, count=1)
    async_db.add(
        ReadingSession(
            user_id=user.id,
            start_die=6,
            manual_die=6,
            active_bandwidth="balanced",
            bandwidth_source="manual",
            active_intent="balanced",
            intent_source="manual",
        )
    )
    await async_db.commit()

    from app.schemas.roll import RollResponse
    from app.services.roll_service import RollService

    response_projected = False
    original_projection = RollService.build_roll_response

    async def record_projection(
        service: RollService,
        *,
        selected_thread: Thread | None = None,
        thread_attrs: dict[str, object] | None = None,
        current_die: int,
        selected_index: int,
        unread_count: int,
        snoozed_count: int,
        issue_id: int | None = None,
        issue_number: str | None = None,
        next_issue_id: int | None = None,
        next_issue_number: str | None = None,
        recommendation_reason_codes: list[str] | None = None,
    ) -> RollResponse:
        nonlocal response_projected
        response_projected = True
        return await original_projection(
            service,
            selected_thread=selected_thread,
            thread_attrs=thread_attrs,
            current_die=current_die,
            selected_index=selected_index,
            unread_count=unread_count,
            snoozed_count=snoozed_count,
            issue_id=issue_id,
            issue_number=issue_number,
            next_issue_id=next_issue_id,
            next_issue_number=next_issue_number,
            recommendation_reason_codes=recommendation_reason_codes,
        )

    async def fail_commit() -> None:
        assert response_projected, "Failure must target the final commit, not initialization"
        raise RuntimeError("synthetic commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(RollService, "build_roll_response", record_projection)
        patch.setattr(async_db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            await auth_client.post("/api/v1/roll/")
    assert response_projected
    await async_db.rollback()
    assert await async_db.scalar(
        select(Event.id).where(Event.type == "roll", Event.session_id.is_not(None))
    ) is None


async def test_plan_read_now_guards_exact_issue_without_retargeting_on_stale_offer(
    option_e: None,
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A reading plan must never silently select a newer issue from the same series."""
    from sqlalchemy import func

    user = await get_or_create_user_async(async_db)
    thread, issues = await _series(async_db, user.id, "Reading plan selection", 1)
    thread_id, first_id, second_id = thread.id, issues[0].id, issues[1].id
    await async_db.commit()

    path = f"/api/v1/threads/{thread_id}/set-pending"
    wrong = await auth_client.post(path, json={"expected_issue_id": second_id})
    assert wrong.status_code == 409
    assert "Refresh the reading plan" in wrong.json()["detail"]
    assert await async_db.scalar(select(func.count(Event.id)).where(Event.type == "roll")) == 0

    selected = await auth_client.post(path, json={"expected_issue_id": first_id})
    assert selected.status_code == 200, selected.text
    assert selected.json()["issue_id"] == first_id
    assert selected.json()["result"] == 0  # Manual selection, not an invented die roll.
    session = await async_db.scalar(
        select(ReadingSession).where(ReadingSession.user_id == user.id)
    )
    assert session is not None
    assert session.pending_thread_id == thread_id
    assert session.pending_issue_id == first_id

    # The plan was open while the first issue became read elsewhere.
    first = await async_db.get(Issue, first_id)
    assert first is not None
    first.status = "read"
    await async_db.commit()

    stale = await auth_client.post(path, json={"expected_issue_id": first_id})
    assert stale.status_code == 409, stale.text
    assert "Refresh the reading plan" in stale.json()["detail"]
    await async_db.refresh(session)
    assert session.pending_thread_id == thread_id
    assert session.pending_issue_id == first_id  # No mutation on stale selection.
    assert await async_db.scalar(select(func.count(Event.id)).where(Event.type == "roll")) == 1
    assert await async_db.scalar(select(Issue.status).where(Issue.id == second_id)) == "unread"
