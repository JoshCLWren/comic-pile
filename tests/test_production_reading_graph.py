"""PostgreSQL replay of sanitized production reading progress and real API offers.

Expected sequences are a separate, reader-intent contract, never captured Roll output.
"""

from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import TypeAdapter
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_reading_execution_settings
from app.models import (
    CatalogIssue, CatalogSeries, Dependency, ExternalIdentity, Issue,
    Thread, ThreadExternalSeriesMapping, User,
)
from app.models.collection_exclusion import CollectionExclusion
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList, CustomCBLOverlapDecision
from app.services.reading_eligibility_service import get_execution_eligibility
from comic_pile.queue import get_bounded_roll_pool_rows
from tests.production_reading_graph_types import (
    ProductionGraphFixture, ProductionReadingContract, RowValue,
)

FIXTURE = Path(__file__).parent / "fixtures" / "production_reading_graph_v1.json"
CONTRACT = Path(__file__).parent / "fixtures" / "production_reading_expectations_v1.json"

THREAD_FIELDS = (
    "id", "title", "format", "issues_remaining", "total_issues",
    "next_unread_issue_id", "queue_position", "status", "is_blocked",
    "queue_position_is_manual", "queue_order_key", "catalog_series_id",
)
ISSUE_FIELDS = ("id", "thread_id", "issue_number", "position", "status", "catalog_issue_id")
ENTRY_FIELDS = (
    "id", "list_id", "issue_id", "position", "gate", "skipped",
    "is_checkpoint", "checkpoint_target_issue_ids",
)


def fixture_data() -> ProductionGraphFixture:
    """Validate every production row and its exact compact schema before replay."""
    return TypeAdapter(ProductionGraphFixture).validate_json(FIXTURE.read_bytes())


def review_contract() -> ProductionReadingContract:
    """Validate the independently authored future-reading contract."""
    return TypeAdapter(ProductionReadingContract).validate_json(CONTRACT.read_bytes())


def records(
    rows: Sequence[Sequence[RowValue]], fields: tuple[str, ...],
) -> list[dict[str, RowValue]]:
    """Unpack statically typed, runtime-validated columns without changing IDs."""
    return [dict(zip(fields, row, strict=True)) for row in rows]


@pytest.fixture
def option_e(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Activate Option E only for this isolated test process."""
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv("OPTION_E_APPROVED_PREVIEW", "local-test-fixture-no-production-approval")
    get_reading_execution_settings.cache_clear()
    yield
    get_reading_execution_settings.cache_clear()


@pytest_asyncio.fixture
async def production_graph(
    async_db: AsyncSession, default_user: User, option_e: None,
) -> AsyncIterator[tuple[int, ProductionGraphFixture]]:
    """Restore a full production-derived graph with foreign keys in test PostgreSQL.

    Only the fixture-owned test user is inserted. Production database credentials
    never appear here, and the ordinary async_db fixture rolls back each test.
    """
    db = async_db
    assert db.bind is not None and db.bind.dialect.name == "postgresql", (
        "Production replay requires isolated PostgreSQL, never SQLite or production"
    )
    data = fixture_data()
    assert data["schema_version"] == 1
    owner = default_user.id

    await restore_production_graph(db, owner, data)
    yield owner, data


async def restore_production_graph(
    db: AsyncSession, owner: int, data: ProductionGraphFixture,
) -> None:
    """Restore validated graph rows and their catalog foreign keys into test PostgreSQL."""
    await db.execute(insert(ExternalIdentity), records(
        data["identities"], ("id", "provider", "entity_type", "external_id"),
    ))
    if data["catalog_series"]:
        await db.execute(insert(CatalogSeries), records(
            data["catalog_series"], ("id", "canonical_external_identity_id"),
        ))
    if data["catalog_issues"]:
        await db.execute(insert(CatalogIssue), records(
            data["catalog_issues"],
            ("id", "canonical_external_identity_id", "catalog_series_id"),
        ))
    threads = records(data["threads"], THREAD_FIELDS)
    pointers = [(row[0], row[5]) for row in data["threads"]]
    for row in threads:
        row.pop("next_unread_issue_id")
    await db.execute(insert(Thread), [{**row, "user_id": owner} for row in threads])
    await db.execute(insert(Issue), records(data["issues"], ISSUE_FIELDS))
    for thread_id, issue_id in pointers:
        if issue_id is not None:
            await db.execute(
                update(Thread).where(Thread.id == thread_id).values(next_unread_issue_id=issue_id)
            )

    await db.execute(insert(CustomCBLList), [
        dict(zip(("id", "name", "mode"), row, strict=True), user_id=owner)
        for row in data["lists"]
    ])
    await db.execute(insert(CustomCBLEntry), records(data["entries"], ENTRY_FIELDS))
    requirements = []
    for dependency_id, source_id, target_id, origin, classification, evidence in data["dependencies"]:
        requirements.append({
            "id": dependency_id, "source_issue_id": source_id, "target_issue_id": target_id,
            "origin": origin, "classification": classification,
            "provenance": "sanitized converted source evidence" if origin == "converted" else None,
            "note": "cbl-order:sanitized" if evidence == "generated" else (
                None if evidence == "unspecified" else "sanitized historical evidence"
            ),
        })
    await db.execute(insert(Dependency), requirements)
    if data["exclusions"]:
        await db.execute(insert(CollectionExclusion), [
            dict(zip(
                ("id", "provider", "external_volume_id", "thread_id", "issue_id"),
                row, strict=True,
            ), user_id=owner)
            for row in data["exclusions"]
        ])
    if data["thread_identity_mappings"]:
        await db.execute(insert(ThreadExternalSeriesMapping), records(
            data["thread_identity_mappings"],
            ("id", "thread_id", "external_identity_id", "status"),
        ))
    if data["overlaps"]:
        await db.execute(insert(CustomCBLOverlapDecision), [
            dict(zip(
                ("id", "list_id", "continuing_external_identity_id",
                 "waiting_external_identity_id"), row, strict=True,
            ), user_id=owner)
            for row in data["overlaps"]
        ])
    await db.flush()



async def assert_offers(
    db: AsyncSession, owner: int, *, offered: tuple[int, ...] = (),
    withheld: tuple[int, ...] = (),
) -> None:
    """Compare actual queued Roll candidates with independently named issue IDs."""
    snapshot = await get_execution_eligibility(db, owner)
    assert snapshot is not None
    offered_ids = {
        result.next_issue_id for thread_id, result in snapshot.threads.items()
        if thread_id in snapshot.candidate_ids()
    }
    for issue_id in offered:
        assert issue_id in offered_ids, f"expected issue {issue_id} to become Roll eligible"
    for issue_id in withheld:
        assert issue_id not in offered_ids, f"prematurely offered issue {issue_id}"


async def advance(db: AsyncSession, issue_id: int) -> None:
    """Simulate one rating's read-state transition against restored actual issues."""
    # Use the same ORM write lifecycle as the rating path. Bulk SQL would
    # bypass after_flush invalidation and accidentally replay cached snapshots.
    issue = await db.get(Issue, issue_id)
    assert issue is not None and issue.status != "read"
    issue.status = "read"
    await db.flush()


@pytest.mark.asyncio
async def test_independent_xmen_future_handoff_sequence(
    production_graph: tuple[int, ProductionGraphFixture], async_db: AsyncSession,
) -> None:
    """X-Men #80, #1/2, UXM #361, X-Men #81 expose no skipped future gates."""
    owner, _ = production_graph
    contract = review_contract()["approved_sequences"]["xmen_1998"]
    await assert_offers(async_db, owner, offered=(contract["steps"][0]["read"],),
                        withheld=tuple(contract["steps"][0]["blocked"]))
    for step in contract["steps"]:
        await advance(async_db, step["read"])
        await assert_offers(async_db, owner, offered=tuple(step["unblocks"]),
                            withheld=tuple(step["still_blocked"]))


@pytest.mark.asyncio
async def test_independent_ultimate_named_handoff_not_global_strictness(
    production_graph: tuple[int, ProductionGraphFixture], async_db: AsyncSession,
) -> None:
    """Ultimate Spider-Man #20 depends on Black Panther #19, not all other titles."""
    owner, _ = production_graph
    contract = review_contract()["approved_sequences"]["ultimate_2025"]
    # Progress from the actual Black Panther frontier, not an invented direct
    # leap to #19. Other Ultimate titles remain independent in this loose list.
    for source_issue_id in contract["progress_to_handoff"]:
        await assert_offers(async_db, owner, withheld=(contract["target"],))
        await advance(async_db, source_issue_id)
    await assert_offers(async_db, owner, offered=(contract["target"],))
    list_row = (await async_db.execute(
        select(CustomCBLList).where(CustomCBLList.name == "Ultimate Universe",
                                    CustomCBLList.user_id == owner)
    )).scalar_one()
    assert list_row.mode == "loose"


@pytest.mark.asyncio
async def test_real_ff_fantastic_four_multiple_handoffs(
    production_graph: tuple[int, ProductionGraphFixture], async_db: AsyncSession,
) -> None:
    """Approved FF/Fantastic Four interleaving is enforced beyond the first step."""
    owner, _ = production_graph
    contract = review_contract()["approved_sequences"]["fantastic_four"]
    for step in contract["steps"]:
        await assert_offers(async_db, owner, offered=(step["read"],),
                            withheld=tuple(step["before_blocked"]))
        await advance(async_db, step["read"])
        await assert_offers(async_db, owner, offered=tuple(step["unblocks"]),
                            withheld=tuple(step["after_blocked"]))


@pytest.mark.asyncio
async def test_actual_roll_queue_selection_and_api_rating(
    production_graph: tuple[int, ProductionGraphFixture], async_db: AsyncSession,
    auth_client: AsyncClient,
) -> None:
    """Roll override and /rate exercise real code on restored PostgreSQL rows."""
    owner, _ = production_graph
    source_id = review_contract()["approved_sequences"]["xmen_1998"]["steps"][0]["read"]
    source = (await async_db.execute(select(Issue).where(Issue.id == source_id))).scalar_one()
    pool = await get_bounded_roll_pool_rows(owner, async_db, 10000)
    assert source.thread_id in {row[0].id for row in pool}
    blocked_id = review_contract()["approved_sequences"]["xmen_1998"]["steps"][0]["blocked"][0]
    blocked = (await async_db.execute(select(Issue).where(Issue.id == blocked_id))).scalar_one()
    assert blocked.thread_id not in {row[0].id for row in pool}
    rolled = await auth_client.post("/api/v1/roll/override", json={"thread_id": source.thread_id})
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["issue_id"] == source_id
    rated = await auth_client.post("/api/v1/rate/", json={"rating": 4.0})
    assert rated.status_code == 200, rated.text
    assert await async_db.scalar(select(Issue.status).where(Issue.id == source_id)) == "read"
    await assert_offers(
        async_db, owner,
        offered=tuple(review_contract()["approved_sequences"]["xmen_1998"]["steps"][0]["unblocks"]),
        withheld=tuple(review_contract()["approved_sequences"]["xmen_1998"]["steps"][0]["still_blocked"]),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("list_name", [
    "JSA Compendium One",
    "Jack Kirby's Fourth World (Omnibus Order)",
    "Justice League International / Breakdowns",
    "Planetary / Authority",
    "Starlin Cosmic",
])
async def test_strict_plan_future_frontier_respects_list_order(
    production_graph: tuple[int, ProductionGraphFixture], async_db: AsyncSession,
    list_name: str,
) -> None:
    """Strict source membership is a separate oracle for later latent frontiers."""
    owner, data = production_graph
    matching = [row for row in data["lists"] if row[1] == list_name]
    assert len(matching) == 1 and matching[0][2] == "strict"
    entries = sorted(
        (row for row in data["entries"] if row[1] == matching[0][0] and not row[5]),
        key=lambda row: row[3],
    )
    status_by_issue = {row[0]: row[4] for row in data["issues"]}
    exclusions = {
        row[4] for row in data["exclusions"] if row[4] is not None
    }
    unread = [row[2] for row in entries
              if status_by_issue[row[2]] != "read" and row[2] not in exclusions]
    assert len(unread) >= 2
    for _ in range(min(5, len(unread) - 1)):
        snapshot = await get_execution_eligibility(async_db, owner)
        assert snapshot is not None
        offered = {
            result.next_issue_id for thread_id, result in snapshot.threads.items()
            if thread_id in snapshot.candidate_ids()
        }
        # Explicit strict intent: a later list issue may never cross an unread predecessor.
        assert not offered.intersection(unread[1:]), (
            f"{list_name}: future issue bypassed {unread[0]}"
        )
        # This branch is deliberately hypothetical. Replay several source
        # placements even when another unrelated plan blocks the real offer,
        # so dormant future frontiers cannot escape our assertions.
        await advance(async_db, unread.pop(0))


@pytest.mark.asyncio
async def test_missing_xmen_prerequisite_is_caught_by_independent_oracle(
    production_graph: tuple[int, ProductionGraphFixture], async_db: AsyncSession,
) -> None:
    """Removing the specific #1/2 handoff must produce a failing expectation.

    This deliberately corrupts only the isolated PostgreSQL test transaction.
    A green current-frontier parity report must never disguise the bad future offer.
    """
    owner, _ = production_graph
    expected = review_contract()["approved_sequences"]["xmen_1998"]["steps"]
    await advance(async_db, expected[0]["read"])
    await assert_offers(async_db, owner, withheld=(2029,))
    requirement = (await async_db.scalars(select(Dependency).where(
        Dependency.source_issue_id == 101875,
        Dependency.target_issue_id == 2029,
        Dependency.origin == "reader",
    ))).one()
    await async_db.delete(requirement)
    await async_db.flush()
    with pytest.raises(AssertionError, match="prematurely offered issue 2029"):
        await assert_offers(async_db, owner, withheld=(2029,))


def test_production_graph_matches_pinned_reviewed_fingerprint() -> None:
    """Any fixture mutation needs a separate contract review and digest update."""
    import hashlib

    data = FIXTURE.read_bytes()
    blob = b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    expected_blob_sha = review_contract()["fixture_git_blob_sha"]
    assert hashlib.sha1(blob).hexdigest() == expected_blob_sha


def test_unresolved_source_reconciliation_fails_parity_signoff() -> None:
    """A clean schema and CI cannot bless the 163/33 unresolved source decisions."""
    from scripts.require_production_reading_intent import incomplete_intent_reasons

    contract = review_contract()
    reasons = incomplete_intent_reasons(contract)
    assert reasons
    assert any("strict_partial_membership" in reason for reason in reasons)
    assert any("reading_list_vs_reading_plan" in reason for reason in reasons)
    assert any("signoff" in reason.lower() for reason in reasons)


@pytest.mark.asyncio
async def test_real_saved_volume_exclusion_survives_hypothetical_reactivation(
    production_graph: tuple[int, ProductionGraphFixture], async_db: AsyncSession,
) -> None:
    """A real saved Comic Vine exclusion still applies if its Thread is reactivated.

    The production reader excluded Absolute Flash by canonical volume, across
    multiple duplicate Threads. This only changes the rolled-back test copy.
    """
    owner, data = production_graph
    assert ("comicvine", "162847") in [row[1:3] for row in data["exclusions"]]
    thread = await async_db.get(Thread, 3156)
    issue = await async_db.get(Issue, 22905)
    assert thread is not None and issue is not None
    thread.status = "active"
    issue.status = "unread"
    await async_db.flush()
    snapshot = await get_execution_eligibility(async_db, owner)
    assert snapshot is not None
    assert issue.id in snapshot.excluded_issue_ids
    assert thread.id not in snapshot.candidate_ids()




@pytest.mark.parametrize(("census", "is_missing"), [
    (None, True),
    ({}, True),
    ({"strict_partial_membership_needing_classification": 0}, True),
    ({
        "strict_partial_membership_needing_classification": 0,
        "reading_list_vs_reading_plan_discrepancies_needing_classification": 0,
    }, True),
    ({
        "strict_partial_membership_needing_classification": 0,
        "reading_list_vs_reading_plan_discrepancies_needing_classification": 0,
        "historical_contradictions": 0,
    }, False),
])
def test_signoff_requires_all_known_zero_census_categories(
    census: dict[str, int] | None, is_missing: bool,
) -> None:
    """Omitting any unresolved category cannot manufacture a signed-off migration."""
    from scripts.require_production_reading_intent import incomplete_intent_reasons

    contract: dict[str, object] = {
        "reader_intent_signoff": "approved",
        "reviewed_source_decisions": [{
            "source": "independent reading plan",
            "discrepancy": "reader reviewed",
            "decision": "classified",
            "reviewed_by": "test reviewer",
        }],
        "fixture_git_blob_sha": review_contract()["fixture_git_blob_sha"],
    }
    if census is not None:
        contract["unresolved_reader_intent"] = census
    reasons = incomplete_intent_reasons(contract)
    assert any("Missing unresolved" in reason for reason in reasons) is is_missing
    if not is_missing:
        assert reasons == []


@pytest.mark.parametrize("invalid_count", [True, "unclassified", None, 1])
def test_signoff_rejects_ambiguous_or_nonzero_census_counts(
    invalid_count: bool | str | int | None,
) -> None:
    """Only explicit integer zero can sign off every named census category."""
    from scripts.require_production_reading_intent import incomplete_intent_reasons

    contract: dict[str, object] = {
        "reader_intent_signoff": "approved",
        "reviewed_source_decisions": [{
            "source": "reviewed source",
            "discrepancy": "reviewed discrepancy",
            "decision": "reviewed decision",
            "reviewed_by": "reviewer",
        }],
        "fixture_git_blob_sha": "reviewed-test-digest",
        "unresolved_reader_intent": {
            "strict_partial_membership_needing_classification": 0,
            "reading_list_vs_reading_plan_discrepancies_needing_classification": 0,
            "historical_contradictions": invalid_count,
        },
    }
    assert any(
        "historical_contradictions" in reason
        for reason in incomplete_intent_reasons(contract)
    )


@pytest.mark.asyncio
async def test_catalog_links_are_preserved_by_fixture_loader(
    async_db: AsyncSession, default_user: User, option_e: None,
) -> None:
    """Re-exported catalog links restore as real foreign keys, not silent NULLs."""
    data = fixture_data()
    mapping = data["thread_identity_mappings"][0]
    thread_id, series_identity_id = mapping[1], mapping[2]
    issue_id = next(row[0] for row in data["issues"] if row[1] == thread_id)
    series_id = max((row[0] for row in data["catalog_series"]), default=0) + 1
    catalog_issue_id = max((row[0] for row in data["catalog_issues"]), default=0) + 1
    issue_identity_id = max(row[0] for row in data["identities"]) + 1
    data["identities"].append(
        (issue_identity_id, "comicvine", "issue", f"fixture-issue-{issue_id}")
    )
    data["catalog_series"].append((series_id, series_identity_id))
    data["catalog_issues"].append((catalog_issue_id, issue_identity_id, series_id))
    data["threads"] = [
        (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], series_id)
        if r[0] == thread_id else r
        for r in data["threads"]
    ]
    data["issues"] = [
        (r[0], r[1], r[2], r[3], r[4], catalog_issue_id)
        if r[0] == issue_id else r
        for r in data["issues"]
    ]
    assert async_db.bind is not None and async_db.bind.dialect.name == "postgresql"
    await restore_production_graph(async_db, default_user.id, data)
    assert await async_db.scalar(
        select(Thread.catalog_series_id).where(Thread.id == thread_id)
    ) == series_id
    assert await async_db.scalar(
        select(Issue.catalog_issue_id).where(Issue.id == issue_id)
    ) == catalog_issue_id
    assert await async_db.scalar(
        select(CatalogIssue.catalog_series_id).where(CatalogIssue.id == catalog_issue_id)
    ) == series_id


def test_production_overlap_census_is_explicit_not_invented() -> None:
    """No production-approved overlap choices existed at export time."""
    assert fixture_data()["overlaps"] == []


# October 26 production conversion: source-order relationships previously
# persisted only as historical diagnostics, now explicitly approved as reader
# prerequisites. This set is not a generated copy of the Roll candidate pool.
RESTORED_SOURCE_ORDER_DEPENDENCIES = frozenset({
    1886, 1723958, 1723961, 1723964, 1723966, 1723967, 1723972,
    1723973, 1723977, 1723978, 1723979, 1723983, 1723986, 1723988,
    1723989, 1723990, 1723993, 1723994, 1723995, 1723996, 1723997,
    1723998, 1724001, 1724002, 1724004, 1724005, 1724006, 1724007,
    1724008, 1724009, 1724010, 1724011, 1724012, 1724013, 1724015,
    1724016, 1724017, 1724018, 1724019, 1724020, 1725384, 1725385,
    1725472, 1725563,
})


def test_approved_old_order_conversion_preserves_exact_source_pairs() -> None:
    """The real 44 accepted links must be executable, with unchanged endpoints."""
    data = fixture_data()
    converted = {
        row[0]: row for row in data["dependencies"]
        if row[0] in RESTORED_SOURCE_ORDER_DEPENDENCIES
    }
    assert set(converted) == RESTORED_SOURCE_ORDER_DEPENDENCIES
    assert all(row[3] == "reader" and row[4] == "A" for row in converted.values())
    # Do not relabel old JLI reversals as explicit reader requirements.
    stale_jli = next(
        (row for row in data["dependencies"] if row[0] == 1725339), None
    )
    assert stale_jli is not None, "Expected stale JLI dependency 1725339 in fixture"
    assert stale_jli[3] == "converted"


@pytest.mark.asyncio
async def test_restored_conversion_future_offer(
    production_graph: tuple[int, ProductionGraphFixture], async_db: AsyncSession,
) -> None:
    """A dormant cross-series Ultimate edge becomes binding at the future frontier.

    Advance the target series inside the isolated production-derived test fixture.
    The target must wait on an unread issue in another series. Reading that
    source removes this particular blocker without globally strict-mode gating
    unrelated Ultimate titles.
    """
    owner, _ = production_graph
    prerequisite_id = 1723958
    source_id, target_id = 23616, 23554
    edge = (await async_db.scalars(select(Dependency).where(
        Dependency.id == prerequisite_id,
    ))).one()
    assert (
        edge.source_issue_id, edge.target_issue_id, edge.origin
    ) == (source_id, target_id, "reader")

    target = (await async_db.scalars(select(Issue).where(Issue.id == target_id))).one()
    await async_db.execute(
        update(Issue).where(
            Issue.thread_id == target.thread_id,
            Issue.position < target.position,
        ).values(status="read")
    )
    await async_db.flush()
    before = await get_execution_eligibility(async_db, owner)
    assert before is not None
    frontier = before.threads[target.thread_id]
    assert frontier.next_issue_id == target_id
    assert any(
        blocker.prerequisite_id == prerequisite_id
        and source_id in blocker.waiting_on_issue_ids
        for blocker in frontier.blockers
    ), "Restored legacy reading boundary was lost from the future Roll frontier"

    await async_db.execute(
        update(Issue).where(Issue.id == source_id).values(status="read")
    )
    await async_db.flush()
    after = await get_execution_eligibility(async_db, owner)
    assert after is not None
    assert after.threads[target.thread_id].next_issue_id == target_id
    assert not any(
        blocker.prerequisite_id == prerequisite_id
        for blocker in after.threads[target.thread_id].blockers
    )
