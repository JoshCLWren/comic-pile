"""Canonical Reading Boundaries explanations backed by the Option E evaluator."""

from collections.abc import Iterator
from dataclasses import replace

import pytest
from httpx import AsyncClient
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
        user_id=1,
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
        assert len(explanation.blockers) == len(state.blockers)


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
