"""Canonical Reading Boundaries explanations backed by the Option E evaluator."""

from collections.abc import Iterator
from dataclasses import replace

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_reading_execution_settings
from app.models import Dependency, Issue, Thread, User
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.repositories.reading_boundary_repository import (
    BoundaryIssueLabels,
    BoundaryListLabels,
    BoundaryPrerequisiteLabels,
    BoundaryReadingListMembership,
    BoundaryShadowLabels,
    BoundaryThreadLabels,
    load_boundary_labels,
)
from app.services.reading_boundary_service import project_boundary_explanation
from app.services.reading_eligibility_service import (
    ReadingEligibilitySnapshot,
    build_eligibility_snapshot,
)
from app.services.reading_list_evaluator import (
    ReadingIssue,
    ReadingList,
    ReadingListEntry,
    ReadingPrerequisite,
    ReadingSnapshot,
    ReadingThread,
    SeriesOverlapDecision,
)
from tests.conftest import get_or_create_user_async

FOURTH_WORLD = "comicvine:volume:fourth-world"
JLI = "comicvine:volume:jli"
MISTER_MIRACLE = "comicvine:volume:mister-miracle"

F1, F2 = 101, 102
J1, M1, J2, M2, J3 = 201, 202, 203, 204, 205

FOURTH_WORLD_ID = 1
JLI_ID = 2
MISTER_MIRACLE_ID = 3
LIST_ID = 10
USER_ID = 1


@pytest.fixture
def option_e(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Enable only the test process with an explicitly non-production reference."""
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv("OPTION_E_APPROVED_PREVIEW", "local-test-fixture-no-production-approval")
    get_reading_execution_settings.cache_clear()
    yield
    get_reading_execution_settings.cache_clear()


def _fixture() -> tuple[ReadingSnapshot, ReadingEligibilitySnapshot, BoundaryShadowLabels]:
    """Build the #1615 JLI/Mister Miracle graph with one historical association."""
    state = ReadingSnapshot(
        user_id=USER_ID,
        threads=(
            ReadingThread(FOURTH_WORLD_ID, name="Fourth World", comicvine_volume_id=FOURTH_WORLD),
            ReadingThread(JLI_ID, name="JLI", comicvine_volume_id=JLI),
            ReadingThread(
                MISTER_MIRACLE_ID,
                name="Mister Miracle",
                comicvine_volume_id=MISTER_MIRACLE,
            ),
        ),
        issues=(
            ReadingIssue(F1, FOURTH_WORLD_ID, 1),
            ReadingIssue(F2, FOURTH_WORLD_ID, 2),
            ReadingIssue(J1, JLI_ID, 1, status="read"),
            ReadingIssue(J2, JLI_ID, 2),
            ReadingIssue(J3, JLI_ID, 3),
            ReadingIssue(M1, MISTER_MIRACLE_ID, 1),
            ReadingIssue(M2, MISTER_MIRACLE_ID, 2),
        ),
        lists=(
            ReadingList(
                LIST_ID,
                "strict",
                (
                    ReadingListEntry(J1),
                    ReadingListEntry(M1),
                    ReadingListEntry(J2),
                    ReadingListEntry(M2),
                    ReadingListEntry(J3),
                ),
                "JLI",
                (SeriesOverlapDecision(JLI, MISTER_MIRACLE),),
            ),
        ),
        prerequisites=(
            ReadingPrerequisite(1, F2, M1, "reader", ("reader authored",)),
        ),
    )
    snapshot = replace(
        build_eligibility_snapshot(state, queued_thread_ids=frozenset({1, 2, 3})),
        active_prerequisite_ids=frozenset({1}),
    )
    labels = BoundaryShadowLabels(
        threads={
            FOURTH_WORLD_ID: BoundaryThreadLabels(1, "Fourth World", "active"),
            JLI_ID: BoundaryThreadLabels(2, "JLI", "active"),
            MISTER_MIRACLE_ID: BoundaryThreadLabels(3, "Mister Miracle", "active"),
        },
        issues={
            issue_id: BoundaryIssueLabels(
                issue_id,
                thread_id,
                {1: "Fourth World", 2: "JLI", 3: "Mister Miracle"}[thread_id],
                number,
            )
            for issue_id, thread_id, number in (
                (F1, 1, "1"),
                (F2, 1, "2"),
                (J1, 2, "1"),
                (J2, 2, "2"),
                (J3, 2, "3"),
                (M1, 3, "1"),
                (M2, 3, "2"),
            )
        },
        lists={LIST_ID: BoundaryListLabels(LIST_ID, "JLI", "strict")},
        prerequisites={
            1: BoundaryPrerequisiteLabels(1, F2, M1, "reader", ("reader authored",)),
            2: BoundaryPrerequisiteLabels(
                2, F1, M1, "converted", ("classification:C", "legacy expansion")
            ),
        },
    )
    return state, snapshot, labels


def test_approved_overlap_explains_j2_available_and_m1_waiting_for_f2() -> None:
    """The explanation follows the evaluator: J2 advances, M1 still names F2."""
    _state, snapshot, labels = _fixture()

    jli = project_boundary_explanation(snapshot, labels, JLI_ID)
    assert jli.state == "available"
    assert jli.next is not None and jli.next.issue.issue_id == J2
    assert jli.blockers == []

    miracle = project_boundary_explanation(snapshot, labels, MISTER_MIRACLE_ID)
    assert miracle.state == "blocked"
    assert miracle.next is not None and miracle.next.issue.issue_id == M1
    assert len(miracle.blockers) == 1
    blocker = miracle.blockers[0]
    assert blocker.kind == "prerequisite"
    assert blocker.origin == "reader_prerequisite"
    assert [issue.issue_id for issue in blocker.waiting_on] == [F2]
    assert blocker.waiting_on[0].label == "Fourth World #2"
    assert blocker.reason == "Reader prerequisite: read Fourth World #2 first"
    assert blocker.editor is not None
    assert blocker.editor.prerequisite_id == 1
    assert blocker.editor.list_id is None


def test_historical_association_is_listed_but_never_a_live_blocker() -> None:
    """Converted or unclassified history cannot become an active boundary."""
    _state, snapshot, labels = _fixture()

    miracle = project_boundary_explanation(snapshot, labels, MISTER_MIRACLE_ID)

    assert [blocker.kind for blocker in miracle.blockers] == ["prerequisite"]
    assert [row.kind for row in miracle.historical] == ["converted_prerequisite"]
    assert "Fourth World #1" in miracle.historical[0].label
    assert "Mister Miracle #1" in miracle.historical[0].label
    assert "not an active reading requirement" in miracle.historical[0].detail


def test_list_blocker_names_owned_list_and_links_its_editor() -> None:
    """A strict-order boundary carries the list name and current list editor."""
    state, _snapshot, labels = _fixture()
    strict = replace(
        state,
        lists=(replace(state.lists[0], overlap_decisions=()),),
    )
    snapshot = replace(
        build_eligibility_snapshot(strict, queued_thread_ids=frozenset({1, 2, 3})),
        active_prerequisite_ids=frozenset({1}),
    )

    jli = project_boundary_explanation(snapshot, labels, JLI_ID)

    assert jli.state == "blocked"
    assert jli.blockers[0].kind == "strict_order"
    assert jli.blockers[0].origin == "reading_list"
    assert jli.blockers[0].reason == "Strict order in JLI: read Mister Miracle #1 first"
    assert [issue.issue_id for issue in jli.blockers[0].waiting_on] == [M1]
    assert jli.blockers[0].editor is not None
    assert jli.blockers[0].editor.kind == "reading_list"
    assert jli.blockers[0].editor.list_id == LIST_ID
    assert jli.blockers[0].editor.label == "JLI"


def test_explanations_parity_with_canonical_evaluator() -> None:
    """Every projected state and frontier equals the shared evaluator result."""
    _state, snapshot, labels = _fixture()

    for thread_id, state in snapshot.threads.items():
        explanation = project_boundary_explanation(snapshot, labels, thread_id)
        assert explanation.next is not None
        assert explanation.next.issue.issue_id == state.next_issue_id
        assert (explanation.state == "blocked") is (not state.eligible)
        # One canonical requirement per waiting Issue, in evaluator order, with
        # no target described twice even when several gates point at it.
        canonical_targets = [
            issue_id
            for blocker in state.blockers
            for issue_id in blocker.waiting_on_issue_ids
        ]
        projected_targets = [
            issue.issue_id
            for blocker in explanation.blockers
            for issue in blocker.waiting_on
        ]
        assert projected_targets == list(dict.fromkeys(canonical_targets))


def test_stacked_hold_and_strict_gates_describe_one_requirement() -> None:
    """MQA-ROLL-013: a real hold + strict stack describes its target once."""
    from app.services.reading_eligibility_service import project_blocking_explanation

    # A cross-series strict list where Mister Miracle #1 carries a hold gate.
    # The evaluator itself emits both a ``hold`` and a ``strict_order`` blocker
    # for that frontier, and both wait on the same unread Fourth World issue.
    state = ReadingSnapshot(
        user_id=USER_ID,
        threads=(
            ReadingThread(FOURTH_WORLD_ID, name="Fourth World"),
            ReadingThread(MISTER_MIRACLE_ID, name="Mister Miracle"),
        ),
        issues=(
            ReadingIssue(F1, FOURTH_WORLD_ID, 1),
            ReadingIssue(M1, MISTER_MIRACLE_ID, 1),
        ),
        lists=(
            ReadingList(
                LIST_ID,
                "strict",
                (
                    ReadingListEntry(F1),
                    ReadingListEntry(M1, gate="hold"),
                ),
                "JLI",
            ),
        ),
        prerequisites=(),
    )
    snapshot = build_eligibility_snapshot(
        state,
        queued_thread_ids=frozenset({FOURTH_WORLD_ID, MISTER_MIRACLE_ID}),
    )
    gates = snapshot.threads[MISTER_MIRACLE_ID].blockers
    assert [gate.kind for gate in gates] == ["hold", "strict_order"]
    assert [gate.waiting_on_issue_ids for gate in gates] == [(F1,), (F1,)]
    labels = _fixture()[2]

    boundary = project_boundary_explanation(snapshot, labels, MISTER_MIRACLE_ID)

    assert [issue.issue_id for b in boundary.blockers for issue in b.waiting_on] == [F1]
    assert boundary.summary == "Mister Miracle #1 is waiting on 1 live requirement."
    assert boundary.blockers[0].reason == "Hold in JLI: read Fourth World #1 first"
    assert boundary.blockers[0].editor is not None
    assert boundary.blockers[0].editor.list_id == LIST_ID

    blocking = project_blocking_explanation(snapshot, MISTER_MIRACLE_ID)
    assert [item.issue_id for item in blocking.blocking_dependencies] == [F1]
    assert blocking.is_blocked


def test_distinct_blocking_targets_stay_separately_visible() -> None:
    """Genuinely distinct requirements keep their own description and editor."""
    other_list_id = LIST_ID + 1
    state = ReadingSnapshot(
        user_id=USER_ID,
        threads=(
            ReadingThread(FOURTH_WORLD_ID, name="Fourth World"),
            ReadingThread(MISTER_MIRACLE_ID, name="Mister Miracle"),
        ),
        issues=(
            ReadingIssue(F1, FOURTH_WORLD_ID, 1),
            ReadingIssue(F2, FOURTH_WORLD_ID, 2),
            ReadingIssue(M1, MISTER_MIRACLE_ID, 1),
        ),
        lists=(
            ReadingList(
                LIST_ID,
                "strict",
                (ReadingListEntry(F1), ReadingListEntry(M1)),
                "JLI",
            ),
            ReadingList(
                other_list_id,
                "strict",
                (ReadingListEntry(F2), ReadingListEntry(M1)),
                "Other List",
            ),
        ),
        prerequisites=(),
    )
    snapshot = build_eligibility_snapshot(
        state,
        queued_thread_ids=frozenset({FOURTH_WORLD_ID, MISTER_MIRACLE_ID}),
    )
    gates = snapshot.threads[MISTER_MIRACLE_ID].blockers
    assert [gate.waiting_on_issue_ids for gate in gates] == [(F1,), (F2,)]
    labels = _fixture()[2]

    boundary = project_boundary_explanation(snapshot, labels, MISTER_MIRACLE_ID)

    assert [
        [issue.issue_id for issue in blocker.waiting_on]
        for blocker in boundary.blockers
    ] == [[F1], [F2]]
    assert boundary.summary == "Mister Miracle #1 is waiting on 2 live requirements."
    assert [
        blocker.editor.list_id if blocker.editor is not None else None
        for blocker in boundary.blockers
    ] == [LIST_ID, other_list_id]


@pytest.mark.asyncio
async def test_repository_leaves_ambiguous_composite_volume_empty(
    async_db: AsyncSession,
) -> None:
    """A Thread with several confirmed series never applies one volume to all Issues."""
    owner = User(username="boundary_volume_owner", password_hash="unused")
    other = User(username="boundary_volume_other", password_hash="unused")
    async_db.add_all([owner, other])
    await async_db.flush()
    composite = Thread(user_id=owner.id, title="Composite", format="Comic", queue_position=1)
    single = Thread(user_id=owner.id, title="Single", format="Comic", queue_position=2)
    foreign = Thread(user_id=other.id, title="Foreign", format="Comic", queue_position=1)
    async_db.add_all([composite, single, foreign])
    await async_db.flush()
    composite_issue = Issue(
        thread_id=composite.id, issue_number="1", position=1, status="unread"
    )
    single_issue = Issue(thread_id=single.id, issue_number="1", position=1, status="unread")
    foreign_issue = Issue(thread_id=foreign.id, issue_number="1", position=1, status="unread")
    async_db.add_all([composite_issue, single_issue, foreign_issue])
    first = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="4050-jla",
        metadata_json={"name": "Justice League America"},
    )
    second = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="4050-jli",
        metadata_json={"name": "Justice League International"},
    )
    unambiguous = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="4050-miracle",
        metadata_json={"name": "Mister Miracle"},
    )
    async_db.add_all([first, second, unambiguous])
    await async_db.flush()
    async_db.add_all(
        [
            ThreadExternalSeriesMapping(
                thread_id=composite.id, external_identity_id=first.id, status="confirmed"
            ),
            ThreadExternalSeriesMapping(
                thread_id=composite.id, external_identity_id=second.id, status="confirmed"
            ),
            ThreadExternalSeriesMapping(
                thread_id=single.id, external_identity_id=unambiguous.id, status="confirmed"
            ),
        ]
    )
    await async_db.flush()

    labels = await load_boundary_labels(async_db, owner.id)

    assert labels.threads[composite.id].volume_label is None
    assert labels.issues[composite_issue.id].volume_label is None
    assert labels.threads[single.id].volume_label == "Mister Miracle"
    assert labels.issues[single_issue.id].volume_label == "Mister Miracle"
    assert foreign.id not in labels.threads
    assert foreign_issue.id not in labels.issues


async def _owned_series(
    db: AsyncSession,
    user_id: int,
    title: str,
    position: int,
    count: int = 2,
) -> tuple[Thread, list[Issue]]:
    """Create one active series with natural issue order."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="Comic",
        queue_position=position,
        status="active",
        total_issues=count,
        issues_remaining=count,
    )
    db.add(thread)
    await db.flush()
    issues = [
        Issue(thread_id=thread.id, issue_number=str(index), position=index, status="unread")
        for index in range(1, count + 1)
    ]
    db.add_all(issues)
    await db.flush()
    thread.next_unread_issue_id = issues[0].id
    await db.flush()
    return thread, issues


@pytest.mark.asyncio
async def test_scoped_boundary_labels_keep_both_directions_and_skip_unrelated_edges(
    async_db: AsyncSession,
) -> None:
    """Only incident owner-owned dependencies may enter a requested explanation."""
    owner = User(username="boundary_scope_owner", password_hash="unused")
    foreign = User(username="boundary_scope_foreign", password_hash="unused")
    async_db.add_all([owner, foreign])
    await async_db.flush()
    requested, a_issues = await _owned_series(async_db, owner.id, "Requested", 1)
    related, b_issues = await _owned_series(async_db, owner.id, "Related", 2)
    unrelated, c_issues = await _owned_series(async_db, owner.id, "Unrelated", 3)
    _, foreign_issues = await _owned_series(async_db, foreign.id, "Foreign", 1)
    outbound = Dependency(
        source_issue_id=a_issues[0].id, target_issue_id=b_issues[0].id,
        note="historical outbound",
    )
    inbound = Dependency(
        source_issue_id=b_issues[1].id, target_issue_id=a_issues[1].id,
        origin="converted", classification="C", provenance="historical inbound",
    )
    internal = Dependency(
        source_issue_id=a_issues[0].id, target_issue_id=a_issues[1].id,
        note="historical internal",
    )
    other = Dependency(
        source_issue_id=b_issues[0].id, target_issue_id=c_issues[0].id,
        note="unrelated historical edge",
    )
    cross_owner = Dependency(
        source_issue_id=foreign_issues[0].id,
        target_issue_id=a_issues[0].id,
        note="foreign data must not leak",
    )
    async_db.add_all([outbound, inbound, internal, other, cross_owner])
    await async_db.commit()

    statements: list[tuple[str, object]] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "FROM dependencies" in statement:
            statements.append((statement, parameters))

    event.listen(Engine, "before_cursor_execute", capture)
    try:
        labels = await load_boundary_labels(
            async_db, owner.id, requested_thread_ids={requested.id}
        )
    finally:
        event.remove(Engine, "before_cursor_execute", capture)

    assert set(labels.prerequisites) == {outbound.id, inbound.id, internal.id}
    assert labels.prerequisite_ids_by_thread[requested.id] == tuple(
        sorted((outbound.id, inbound.id, internal.id))
    )
    assert len(statements) == 2
    # The requested Thread restriction must be in the executed SQL, not
    # applied later to 75k retrieved Dependency objects in Python.
    assert any("boundary_source_issue.thread_id IN (" in sql for sql, _ in statements)
    assert any("boundary_target_issue.thread_id IN (" in sql for sql, _ in statements)
    for sql, params in statements:
        assert "WHERE" in sql.upper()
        if isinstance(params, dict):
            values = tuple(str(value) for value in params.values())
        elif isinstance(params, (tuple, list)):
            values = tuple(str(value) for value in params)
        else:
            pytest.fail("Unexpected database parameter representation")
        assert str(requested.id) in values

    both = await load_boundary_labels(
        async_db, owner.id, requested_thread_ids={requested.id, related.id}
    )
    assert set(both.prerequisites) == {outbound.id, inbound.id, internal.id, other.id}
    assert all(edge_id not in both.prerequisite_ids_by_thread[unrelated.id]
               for edge_id in (outbound.id, inbound.id, internal.id))


@pytest.mark.asyncio
async def test_api_returns_named_live_blocker_and_excludes_history(
    option_e: None,
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """The authenticated route names the authored prerequisite, not old adjacency."""
    user = await get_or_create_user_async(async_db)
    other = User(username="boundary_api_other", password_hash="unused")
    async_db.add(other)
    await async_db.flush()
    fourth, fourth_issues = await _owned_series(async_db, user.id, "Fourth World", 1)
    miracle, miracle_issues = await _owned_series(async_db, user.id, "Mister Miracle", 2)
    foreign, _ = await _owned_series(async_db, other.id, "Foreign", 1)
    async_db.add_all(
        [
            Dependency(
                source_issue_id=fourth_issues[1].id,
                target_issue_id=miracle_issues[0].id,
                origin="reader",
                classification="A",
                provenance="Explicit reader prerequisite",
            ),
            Dependency(
                source_issue_id=fourth_issues[0].id,
                target_issue_id=miracle_issues[0].id,
                note="Old reading plan checkpoint",
            ),
        ]
    )
    await async_db.commit()
    miracle_id, foreign_id = miracle.id, foreign.id

    response = await auth_client.get(f"/api/v1/reading-boundaries/{miracle_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "blocked"
    assert [issue["issue_number"] for issue in body["blockers"][0]["waiting_on"]] == ["2"]
    assert body["blockers"][0]["waiting_on"][0]["thread_title"] == "Fourth World"
    assert "Reader prerequisite" in body["blockers"][0]["reason"]
    assert body["blockers"][0]["editor"]["prerequisite_id"] is not None
    assert len(body["historical"]) == 1
    assert body["historical"][0]["kind"] == "legacy_dependency"
    assert "not an active reading requirement" in body["historical"][0]["detail"]

    # V2 is a clean versioned contract: no retired field or historical SELECT.
    dependency_sql: list[tuple[str, tuple[str, ...]]] = []

    def capture_v2(conn, cursor, statement, parameters, context, executemany):
        if "FROM dependencies" in statement:
            if isinstance(parameters, dict):
                binds = tuple(str(value) for value in parameters.values())
            elif isinstance(parameters, (list, tuple)):
                binds = tuple(str(value) for value in parameters)
            else:
                binds = ()
            dependency_sql.append((statement, binds))

    event.listen(Engine, "before_cursor_execute", capture_v2)
    try:
        canonical_response = await auth_client.get(
            f"/api/v2/reading-boundaries/{miracle_id}"
        )
        canonical_batch = await auth_client.post(
            "/api/v2/reading-boundaries",
            json={"thread_ids": [fourth.id, miracle_id]},
        )
    finally:
        event.remove(Engine, "before_cursor_execute", capture_v2)

    assert canonical_response.status_code == 200, canonical_response.text
    canonical = canonical_response.json()
    assert "historical" not in canonical
    assert canonical["state"] == body["state"]
    assert canonical["blockers"] == body["blockers"]
    assert canonical["next"] == body["next"]
    assert canonical_batch.status_code == 200, canonical_batch.text
    assert set(canonical_batch.json()["threads"]) == {str(fourth.id), str(miracle_id)}
    assert all(
        "historical" not in explanation
        for explanation in canonical_batch.json()["threads"].values()
    )
    # Only get_execution_eligibility's explicit reader-origin query is allowed.
    # The boundary label loader must never fetch converted or unclassified rows.
    assert all("DEPENDENCIES.ORIGIN =" in query.upper().split("WHERE", 1)[1]
               for query, _ in dependency_sql)
    assert all("reader" in binds for _, binds in dependency_sql)
    assert len(dependency_sql) <= 2

    hidden = await auth_client.get(f"/api/v1/reading-boundaries/{foreign_id}")
    assert hidden.status_code == 404

    batch = await auth_client.post(
        "/api/v1/reading-boundaries",
        json={"thread_ids": [fourth.id, miracle_id]},
    )
    assert batch.status_code == 200, batch.text
    assert set(batch.json()["threads"]) == {str(fourth.id), str(miracle_id)}
    assert batch.json()["threads"][str(miracle_id)]["state"] == "blocked"

    missing = await auth_client.post(
        "/api/v1/reading-boundaries",
        json={"thread_ids": [foreign_id]},
    )
    assert missing.status_code == 404


def test_owned_list_names_and_modes_appear_on_next_and_waiting_issues() -> None:
    """Owned list membership labels survive projection onto next and waiting Issues."""
    _state, snapshot, labels = _fixture()

    membership = BoundaryReadingListMembership(
        list_id=LIST_ID, name="JLI", mode="strict"
    )
    new_issues = dict(labels.issues)
    for issue_id in (F2, J2, M1):
        row = new_issues[issue_id]
        new_issues[issue_id] = replace(row, reading_lists=[membership])
    labels = replace(labels, issues=new_issues)

    jli = project_boundary_explanation(snapshot, labels, JLI_ID)
    assert jli.next is not None
    assert jli.next.issue.reading_lists[0].name == "JLI"
    assert jli.next.issue.reading_lists[0].mode == "strict"

    miracle = project_boundary_explanation(snapshot, labels, MISTER_MIRACLE_ID)
    assert miracle.next is not None
    assert miracle.next.issue.reading_lists[0].name == "JLI"
    assert miracle.next.issue.reading_lists[0].mode == "strict"
    assert miracle.blockers
    assert miracle.blockers[0].waiting_on[0].reading_lists[0].name == "JLI"
    assert miracle.blockers[0].waiting_on[0].reading_lists[0].mode == "strict"


@pytest.mark.asyncio
async def test_api_returns_unavailable_when_option_e_disabled_single(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A disabled Option E explains one owned series as unavailable."""
    user = await get_or_create_user_async(async_db)
    thread, _issues = await _owned_series(async_db, user.id, "Fourth World", 1)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/reading-boundaries/{thread.id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "unavailable"
    assert body["next"] is None
    assert body["blockers"] == []
    assert body["historical"] == []


@pytest.mark.asyncio
async def test_api_returns_unavailable_when_option_e_disabled_batch(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A disabled Option E explains every requested owned series as unavailable."""
    user = await get_or_create_user_async(async_db)
    first, _ = await _owned_series(async_db, user.id, "First", 1)
    second, _ = await _owned_series(async_db, user.id, "Second", 2)
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/reading-boundaries",
        json={"thread_ids": [first.id, second.id]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["threads"]) == {str(first.id), str(second.id)}
    for thread in (first, second):
        assert body["threads"][str(thread.id)]["state"] == "unavailable"


@pytest.mark.asyncio
async def test_api_includes_owned_list_names_and_modes_on_issues(
    option_e: None,
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Owned list names and modes appear on next and waiting Issues."""
    user = await get_or_create_user_async(async_db)
    other = User(username="boundary_list_other", password_hash="unused")
    async_db.add(other)
    await async_db.flush()
    fourth, fourth_issues = await _owned_series(async_db, user.id, "Fourth World", 1)
    miracle, miracle_issues = await _owned_series(async_db, user.id, "Mister Miracle", 2)

    cbl = CustomCBLList(user_id=user.id, name="JLI", mode="strict")
    async_db.add(cbl)
    await async_db.flush()
    async_db.add_all(
        [
            CustomCBLEntry(
                list_id=cbl.id, issue_id=fourth_issues[1].id, position=1, gate="none"
            ),
            CustomCBLEntry(
                list_id=cbl.id, issue_id=miracle_issues[0].id, position=2, gate="none"
            ),
        ]
    )
    async_db.add(
        Dependency(
            source_issue_id=fourth_issues[1].id,
            target_issue_id=miracle_issues[0].id,
            origin="reader",
            classification="A",
            provenance="Explicit reader prerequisite",
        )
    )
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/reading-boundaries/{miracle.id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["next"]["issue"]["reading_lists"][0]["name"] == "JLI"
    assert body["next"]["issue"]["reading_lists"][0]["mode"] == "strict"
    assert body["blockers"][0]["waiting_on"][0]["reading_lists"][0]["name"] == "JLI"
    assert body["blockers"][0]["waiting_on"][0]["reading_lists"][0]["mode"] == "strict"


@pytest.mark.parametrize("requirements", [(F2,), (F2, F1)])
def test_duplicate_requirements_keep_each_distinct_issue_once(
    requirements: tuple[int, ...],
) -> None:
    """Hold and reader origins cannot duplicate or hide canonical requirements."""
    from app.services.reading_eligibility_service import project_blocking_explanation
    from app.services.reading_list_evaluator import Blocker, ThreadEligibility

    _state, snapshot, labels = _fixture()
    original = (
        Blocker("hold", LIST_ID, (F2,)),
        Blocker("prerequisite", None, requirements, prerequisite_id=1, origin="reader"),
    )
    snapshot = replace(
        snapshot,
        threads={MISTER_MIRACLE_ID: ThreadEligibility(MISTER_MIRACLE_ID, M1, original)},
    )
    boundary = project_boundary_explanation(snapshot, labels, MISTER_MIRACLE_ID)
    waiting = [issue.issue_id for blocker in boundary.blockers for issue in blocker.waiting_on]
    assert waiting == ([F2] if requirements == (F2,) else [F2, F1])
    assert boundary.blockers[0].reason.startswith("Hold in JLI")
    assert boundary.blockers[0].editor is not None
    assert boundary.blockers[0].editor.list_id == LIST_ID
    explanation = project_blocking_explanation(snapshot, MISTER_MIRACLE_ID)
    assert [item.issue_id for item in explanation.blocking_dependencies] == waiting
    assert explanation.is_blocked
    assert snapshot.threads[MISTER_MIRACLE_ID].blockers == original
