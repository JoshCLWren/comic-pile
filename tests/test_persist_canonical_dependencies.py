"""Regression coverage for the canonical Dependency backfill script.

`scripts/persist_canonical_dependencies.py` reduces ContinuityRule semantics
into canonical issue-to-issue Dependency rows for the Roll cutover in
`docs/READING_GRAPH_RUNTIME_AUDIT.md` sections 4.1 and 4.2:

- a rule-native ``item_read`` issue-to-issue rule becomes ``Dependency(source, target)``;
- each ``converged`` prerequisite becomes ``Dependency(prerequisite, rule.target)``.

The ``converged`` direction is the load-bearing assertion: production converged
rules are self-referential (``source_id == target_id``) and ``source_id`` is
decorative, so writing ``Dependency(rule.source_id, prerequisite)`` would invert
every convergence gate and block the wrong frontier.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from tests.conftest import get_or_create_user_async


def _load_script_module(name: str) -> ModuleType:
    """Dynamically load a module from the repository ``scripts`` directory."""
    spec = importlib.util.spec_from_file_location(
        name,
        str(Path(__file__).parent.parent / "scripts" / f"{name}.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_script = _load_script_module("persist_canonical_dependencies")
sys.modules["persist_canonical_dependencies"] = _script


async def _issue(db: AsyncSession, *, user_id: int, title: str, position: int) -> Issue:
    """Create a one-issue Thread and return its frontier Issue."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        queue_position=position,
        status="active",
        total_issues=1,
        issues_remaining=1,
        reading_progress="unstarted",
    )
    db.add(thread)
    await db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = issue.id
    await db.flush()
    return issue


@pytest.mark.asyncio
async def test_item_read_rule_becomes_canonical_dependency(async_db: AsyncSession) -> None:
    """A rule-native item_read rule persists its own source-to-target edge."""
    user = await get_or_create_user_async(async_db)
    source = await _issue(async_db, user_id=user.id, title="Prereq", position=1)
    target = await _issue(async_db, user_id=user.id, title="Gated", position=2)
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=source.id,
            target_type="issue",
            target_id=target.id,
            satisfaction_type="item_read",
            note="continuity-plan:1",
        )
    )
    await async_db.commit()

    assert await _script.persist_canonical_constraints(async_db) == 1

    row = (
        await async_db.execute(
            select(Dependency).where(
                Dependency.source_issue_id == source.id,
                Dependency.target_issue_id == target.id,
            )
        )
    ).scalar_one()
    # The origin marker carries no single-plan owner and is canonical.
    assert row.note == "canonical:compiled-hard-constraint"
    await async_db.commit()


@pytest.mark.asyncio
async def test_converged_rule_persists_prerequisite_into_rule_target(
    async_db: AsyncSession,
) -> None:
    """Each converged prerequisite becomes an edge into the rule target."""
    user = await get_or_create_user_async(async_db)
    first = await _issue(async_db, user_id=user.id, title="First", position=1)
    second = await _issue(async_db, user_id=user.id, title="Second", position=2)
    gated = await _issue(async_db, user_id=user.id, title="Gated", position=3)
    # Self-referential converged rule, matching production shape (audit 1.1).
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=gated.id,
            target_type="issue",
            target_id=gated.id,
            satisfaction_type="converged",
            convergence_targets=[
                {"type": "issue", "id": first.id},
                {"type": "issue", "id": second.id},
            ],
            note="continuity-plan:2",
        )
    )
    await async_db.commit()

    assert await _script.persist_canonical_constraints(async_db) == 2

    edges = {
        (row.source_issue_id, row.target_issue_id)
        for row in (
            await async_db.execute(
                select(Dependency).where(Dependency.target_issue_id == gated.id)
            )
        )
        .scalars()
        .all()
    }
    assert edges == {(first.id, gated.id), (second.id, gated.id)}
    # The decorative self-referential source must never become an edge source.
    assert (gated.id, first.id) not in edges
    assert (gated.id, second.id) not in edges
    await async_db.commit()


@pytest.mark.asyncio
async def test_backfill_is_idempotent(async_db: AsyncSession) -> None:
    """Re-running the backfill inserts nothing and creates no duplicate edges."""
    user = await get_or_create_user_async(async_db)
    source = await _issue(async_db, user_id=user.id, title="Prereq", position=1)
    target = await _issue(async_db, user_id=user.id, title="Gated", position=2)
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=source.id,
            target_type="issue",
            target_id=target.id,
            satisfaction_type="item_read",
        )
    )
    await async_db.commit()

    assert await _script.persist_canonical_constraints(async_db) == 1
    assert await _script.persist_canonical_constraints(async_db) == 0
    assert await _script.persist_canonical_constraints(async_db) == 0
    await async_db.commit()
