"""PostgreSQL rollback evidence for the Option E dry-run entrypoint."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.services.reading_list_authoring import load_authoring_snapshot
from app.services.reading_list_conversion_plan import (
    ConversionIntent,
    ListDecision,
    snapshot_fingerprint,
)
from scripts.plan_option_e_conversion import _load_evidence, run


async def test_rehearsal_applies_then_rolls_back(
    async_db: AsyncSession, default_user: User
) -> None:
    """Observed strict-list blocking matches the preview and never persists."""
    owner_id = default_user.id
    threads = [
        Thread(user_id=owner_id, title=f"Rehearsal {i}", format="Comic", queue_position=i)
        for i in range(2)
    ]
    async_db.add_all(threads)
    await async_db.flush()
    issues = [Issue(thread_id=t.id, issue_number="1", position=1, status="unread") for t in threads]
    async_db.add_all(issues)
    reading_list = CustomCBLList(user_id=owner_id, name="Rehearsal", mode="loose")
    async_db.add(reading_list)
    await async_db.flush()
    async_db.add_all(
        [
            CustomCBLEntry(list_id=reading_list.id, issue_id=issue.id, position=i)
            for i, issue in enumerate(issues)
        ]
    )
    list_id = reading_list.id
    await async_db.commit()
    snapshot, _ = await load_authoring_snapshot(async_db, owner_id)
    evidence = await _load_evidence(async_db, owner_id, snapshot)
    intent = ConversionIntent(
        snapshot_fingerprint(snapshot, evidence), lists=(ListDecision(list_id, "strict"),)
    )
    result = await run(async_db, owner_id, intent, mode="rehearse", acknowledge_rollback=True)
    assert result["valid"] is True
    rehearsal = result["rehearsal"]
    assert isinstance(rehearsal, dict)
    assert rehearsal["matches_manifest"] is True
    assert result["committed"] is False
    assert (
        await async_db.scalar(select(CustomCBLList.mode).where(CustomCBLList.id == list_id))
        == "loose"
    )


async def test_preflight_works_in_postgres_read_only_transaction(
    async_db: AsyncSession, default_user: User
) -> None:
    """The complete loader and manifest path need no database writes."""
    owner_id = default_user.id
    await async_db.rollback()
    await async_db.execute(text("SET TRANSACTION READ ONLY"))
    snapshot, _ = await load_authoring_snapshot(async_db, owner_id)
    evidence = await _load_evidence(async_db, owner_id, snapshot)
    result = await run(
        async_db,
        owner_id,
        ConversionIntent(snapshot_fingerprint(snapshot, evidence)),
        mode="preflight",
        acknowledge_rollback=False,
    )
    assert result["valid"] is True
    assert await async_db.scalar(text("SHOW transaction_read_only")) == "on"
    await async_db.rollback()


async def test_unknown_mode_refuses_before_loading(async_db: AsyncSession) -> None:
    """A misspelled mode never accidentally enters the write rehearsal."""
    with pytest.raises(ValueError, match="Unknown"):
        await run(async_db, 1, ConversionIntent("unused"), mode="apply", acknowledge_rollback=True)


@pytest.mark.parametrize("populated_plans", [0, 1, 2])
async def test_multiple_linked_plans_are_ambiguous_even_with_shared_or_empty_lanes(
    async_db: AsyncSession, default_user: User, populated_plans: int
) -> None:
    """Two plans cannot collapse into one lane because both call it main."""
    from app.models.continuity_plan import ContinuityPlan
    from app.models.reading_plan_membership import ReadingPlanIssue, ReadingPlanSource
    from app.services.reading_list_conversion_plan import build_manifest
    from scripts.plan_option_e_conversion import load_project_evidence

    owner_id = default_user.id
    thread = Thread(user_id=owner_id, title="Shared lane", format="Comic", queue_position=1)
    reading_list = CustomCBLList(user_id=owner_id, name="Shared lane", mode="loose")
    plans = [ContinuityPlan(user_id=owner_id, name=f"Plan {i}") for i in range(2)]
    async_db.add_all([thread, reading_list, *plans])
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()
    async_db.add(CustomCBLEntry(list_id=reading_list.id, issue_id=issue.id, position=1))
    for i, plan in enumerate(plans):
        async_db.add(
            ReadingPlanSource(
                plan_id=plan.id, custom_cbl_list_id=reading_list.id, raw_source_path=f"source-{i}"
            )
        )
        if i < populated_plans:
            async_db.add(
                ReadingPlanIssue(
                    plan_id=plan.id,
                    occurrence_id="entry",
                    issue_id=issue.id,
                    lane_id="main",
                    display_position=1,
                )
            )
    await async_db.flush()
    snapshot, _ = await load_authoring_snapshot(async_db, owner_id)
    projects = await load_project_evidence(async_db, owner_id, snapshot)
    assert projects[0].plan_lane_count == 2
    from app.services.reading_list_conversion_plan import ConversionEvidence

    evidence = ConversionEvidence(projects=projects)
    manifest = build_manifest(
        snapshot,
        evidence,
        ConversionIntent(
            snapshot_fingerprint(snapshot, evidence),
            lists=(ListDecision(reading_list.id, "loose"),),
        ),
    )
    assert not manifest.valid
    assert "ambiguous_placement" in {row.code for row in manifest.refusals}
