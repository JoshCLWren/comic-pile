"""Tests for persistent account-wide Roll tag exclusions (issue #3033).

Covers the full closure-critical contract:
- persistent account-wide excluded tag IDs (not ReadingSession-only)
- roll-pool eligibility evaluated on the next unread issue's effective tags
- direct, thread-inherited, and plan-inherited filtering
- mid-roll exclusion with neutral auto-reroll (no snooze/backoff/bandwidth/
  rating/recommendation side effects)
- add/remove management directly from Roll, including empty-pool explanation
- private exclusions stay user-scoped; global tags excludable per user
- ordinary snooze and skip behavior unchanged
- bulk effective-tag resolution without per-candidate lookups
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
from app.database import get_db
from app.main import app
from app.models import (
    ContinuityPlan,
    Issue,
    ReadingPlanIssue,
    ReadingSession,
    RollTagExclusion,
    Tag,
    TagAssignment,
    TasteSignal,
    Thread,
    User,
)
from app.models.event import Event
from app.services.roll_tag_exclusion_service import RollTagExclusionService
from comic_pile.queue import partition_pool_by_tag_exclusions
from tests.conftest import _create_async_db_override


@pytest.fixture(autouse=True)
def enable_test_environment() -> Iterator[None]:
    """Enable test environment for all tests in this module."""
    original = os.environ.get("TEST_ENVIRONMENT")
    os.environ["TEST_ENVIRONMENT"] = "true"
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("TEST_ENVIRONMENT", None)
        else:
            os.environ["TEST_ENVIRONMENT"] = original


@pytest.fixture(autouse=True)
def clear_config_cache() -> Iterator[None]:
    """Clear cached settings before and after each test."""
    from app.config import clear_settings_cache

    clear_settings_cache()
    yield
    clear_settings_cache()


async def _sync_id_sequence(db: AsyncSession, table_name: str) -> None:
    """Advance a table's id sequence after explicit inserts."""
    await db.execute(
        text(
            "SELECT setval("
            f"pg_get_serial_sequence('{table_name}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table_name}), 1), true)"
        )
    )


@pytest_asyncio.fixture(scope="function")
async def exclusion_user(async_db: AsyncSession) -> AsyncIterator[User]:
    """Create the primary non-admin test user."""
    now = datetime.now(UTC)
    user = User(id=2, username="exclusion_user", created_at=now)
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)
    await _sync_id_sequence(async_db, "users")
    yield user


@pytest_asyncio.fixture(scope="function")
async def other_user(async_db: AsyncSession) -> AsyncIterator[User]:
    """Create a second non-admin test user for scoping checks."""
    now = datetime.now(UTC)
    user = User(id=3, username="exclusion_other", created_at=now)
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)
    await _sync_id_sequence(async_db, "users")
    yield user


@pytest_asyncio.fixture(scope="function")
async def user_auth_client(
    async_db: AsyncSession, exclusion_user: User
) -> AsyncIterator[AsyncClient]:
    """Authenticated client for the primary test user."""
    app.dependency_overrides[get_db] = await _create_async_db_override(async_db)
    transport = ASGITransport(app=app)
    ac = AsyncClient(transport=transport, base_url="http://test")
    csrf_token = generate_csrf_token()
    ac.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    ac.headers.update({CSRF_HEADER_NAME: csrf_token})
    token = create_access_token(data={"sub": exclusion_user.username, "jti": "test"})
    ac.headers.update({"Authorization": f"Bearer {token}"})
    try:
        yield ac
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def other_auth_client(
    async_db: AsyncSession, other_user: User
) -> AsyncIterator[AsyncClient]:
    """Authenticated client for the second test user."""
    app.dependency_overrides[get_db] = await _create_async_db_override(async_db)
    transport = ASGITransport(app=app)
    ac = AsyncClient(transport=transport, base_url="http://test")
    csrf_token = generate_csrf_token()
    ac.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    ac.headers.update({CSRF_HEADER_NAME: csrf_token})
    token = create_access_token(data={"sub": other_user.username, "jti": "test"})
    ac.headers.update({"Authorization": f"Bearer {token}"})
    try:
        yield ac
    finally:
        app.dependency_overrides.clear()


async def _create_thread(
    db: AsyncSession,
    owner: User,
    thread_id: int,
    title: str,
    queue_position: int,
    *,
    with_issue: bool = True,
) -> tuple[Thread, Issue | None]:
    """Create an active thread with an optional tracked next unread issue."""
    now = datetime.now(UTC)
    thread = Thread(
        id=thread_id,
        title=title,
        format="Comic",
        issues_remaining=5,
        queue_position=queue_position,
        status="active",
        user_id=owner.id,
        created_at=now,
        total_issues=10 if with_issue else None,
        reading_progress="in_progress" if with_issue else None,
    )
    db.add(thread)
    await db.flush()
    issue: Issue | None = None
    if with_issue:
        issue = Issue(
            thread_id=thread.id,
            issue_number="1",
            position=1,
            status="unread",
            created_at=now,
        )
        db.add(issue)
        await db.flush()
        thread.next_unread_issue_id = issue.id
        await db.flush()
    await _sync_id_sequence(db, "threads")
    await _sync_id_sequence(db, "issues")
    return thread, issue


async def _create_private_tag(
    db: AsyncSession, owner: User, name: str = "Physical"
) -> Tag:
    """Create a private tag owned by a user."""
    now = datetime.now(UTC)
    tag = Tag(
        name=name,
        normalized_name=name.strip().lower(),
        scope="private",
        owner_user_id=owner.id,
        color="#DC2626",
        created_at=now,
        updated_at=now,
    )
    db.add(tag)
    await db.flush()
    await _sync_id_sequence(db, "tags")
    return tag


async def _create_global_tag(db: AsyncSession, name: str = "Global Pick") -> Tag:
    """Create a global tag with no owner."""
    now = datetime.now(UTC)
    tag = Tag(
        name=name,
        normalized_name=name.strip().lower(),
        scope="global",
        owner_user_id=None,
        color="#DC2626",
        created_at=now,
        updated_at=now,
    )
    db.add(tag)
    await db.flush()
    await _sync_id_sequence(db, "tags")
    return tag


async def _assign_tag(
    db: AsyncSession, tag: Tag, target_type: str, target_id: int
) -> None:
    """Attach a tag to a target."""
    db.add(TagAssignment(tag_id=tag.id, target_type=target_type, target_id=target_id))
    await db.flush()


async def _create_plan_with_issue(
    db: AsyncSession, owner: User, issue: Issue, plan_id: int = 1
) -> ContinuityPlan:
    """Create a reading plan owned by a user containing one issue."""
    now = datetime.now(UTC)
    plan = ContinuityPlan(
        id=plan_id,
        user_id=owner.id,
        name="My Plan",
        ordering_mode="informational",
        nodes_json=[],
        lanes_json=[],
        created_at=now,
        updated_at=now,
    )
    db.add(plan)
    await db.flush()
    db.add(
        ReadingPlanIssue(
            plan_id=plan.id,
            occurrence_id="occ-1",
            issue_id=issue.id,
            lane_id="lane-1",
            display_position=1,
        )
    )
    await db.flush()
    await _sync_id_sequence(db, "continuity_plans")
    return plan


async def _get_session(db: AsyncSession, user: User) -> ReadingSession | None:
    """Return the user's active reading session, if any."""
    result = await db.execute(
        select(ReadingSession)
        .where(ReadingSession.user_id == user.id)
        .where(ReadingSession.ended_at.is_(None))
        .order_by(ReadingSession.started_at.desc())
    )
    return result.scalars().first()


class TestExclusionPersistence:
    """Exclusions are persistent and account-wide, not session-only."""

    async def test_add_and_list_exclusions(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """POST persists the exclusion and GET lists it back."""
        tag = await _create_private_tag(async_db, exclusion_user)
        await async_db.commit()

        resp = await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == tag.id

        list_resp = await user_auth_client.get("/api/v1/roll/tag-exclusions/")
        assert list_resp.status_code == 200
        assert [t["id"] for t in list_resp.json()["excluded_tags"]] == [tag.id]

        stored = await async_db.execute(
            select(RollTagExclusion).where(
                RollTagExclusion.user_id == exclusion_user.id
            )
        )
        assert [row.tag_id for row in stored.scalars().all()] == [tag.id]

    async def test_add_is_idempotent(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """Excluding an already-excluded tag returns it unchanged."""
        tag = await _create_private_tag(async_db, exclusion_user)
        await async_db.commit()

        first = await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        second = await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        assert first.status_code == 200
        assert second.status_code == 200

        stored = await async_db.execute(
            select(func.count())
            .select_from(RollTagExclusion)
            .where(RollTagExclusion.user_id == exclusion_user.id)
        )
        assert stored.scalar() == 1

    async def test_exclusion_survives_roll_cycle(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """The exclusion is still active after rolling and resolving pending."""
        tag = await _create_private_tag(async_db, exclusion_user)
        thread_a, _ = await _create_thread(async_db, exclusion_user, 1, "Alpha", 1)
        thread_b, _ = await _create_thread(async_db, exclusion_user, 2, "Beta", 2)
        assert thread_a.id != thread_b.id
        await async_db.commit()

        await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        roll_resp = await user_auth_client.post("/api/roll/")
        assert roll_resp.status_code == 200
        await user_auth_client.post("/api/roll/dismiss-pending")

        list_resp = await user_auth_client.get("/api/v1/roll/tag-exclusions/")
        assert [t["id"] for t in list_resp.json()["excluded_tags"]] == [tag.id]

        session = await _get_session(async_db, exclusion_user)
        assert session is not None
        assert not (session.snoozed_thread_ids or [])
        assert not (session.skipped_thread_ids or [])

    async def test_remove_makes_candidates_eligible_immediately(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """Removing the exclusion restores the candidate to the pool."""
        tag = await _create_private_tag(async_db, exclusion_user)
        thread_a, issue_a = await _create_thread(async_db, exclusion_user, 1, "Alpha", 1)
        assert issue_a is not None
        await _assign_tag(async_db, tag, "Issue", issue_a.id)
        await async_db.commit()

        await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        empty_resp = await user_auth_client.post("/api/roll/")
        assert empty_resp.status_code == 400

        del_resp = await user_auth_client.delete(
            f"/api/v1/roll/tag-exclusions/{tag.id}/"
        )
        assert del_resp.status_code == 200

        roll_resp = await user_auth_client.post("/api/roll/")
        assert roll_resp.status_code == 200
        assert roll_resp.json()["thread_id"] == thread_a.id

    async def test_remove_missing_exclusion_is_404(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """Removing a tag that was never excluded reports not found."""
        tag = await _create_private_tag(async_db, exclusion_user)
        await async_db.commit()

        resp = await user_auth_client.delete(
            f"/api/v1/roll/tag-exclusions/{tag.id}/"
        )
        assert resp.status_code == 404

    async def test_unknown_tag_is_404(
        self, user_auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Excluding a tag that does not exist reports not found."""
        resp = await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": 999999}
        )
        assert resp.status_code == 404


class TestRollEligibility:
    """Roll-pool eligibility evaluates next-unread-issue effective tags."""

    async def test_direct_issue_tag_excludes_candidate(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """A candidate whose next issue carries an excluded tag is ineligible."""
        tag = await _create_private_tag(async_db, exclusion_user)
        _thread_a, issue_a = await _create_thread(
            async_db, exclusion_user, 1, "Alpha", 1
        )
        thread_b, _ = await _create_thread(async_db, exclusion_user, 2, "Beta", 2)
        assert issue_a is not None
        await _assign_tag(async_db, tag, "Issue", issue_a.id)
        await async_db.commit()

        await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        resp = await user_auth_client.post("/api/roll/")
        assert resp.status_code == 200
        assert resp.json()["thread_id"] == thread_b.id

    async def test_inherited_thread_tag_excludes_candidate(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """A tag inherited from the thread filters the next unread issue."""
        tag = await _create_private_tag(async_db, exclusion_user)
        thread_a, _ = await _create_thread(async_db, exclusion_user, 1, "Alpha", 1)
        thread_b, _ = await _create_thread(async_db, exclusion_user, 2, "Beta", 2)
        await _assign_tag(async_db, tag, "Thread", thread_a.id)
        await async_db.commit()

        await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        resp = await user_auth_client.post("/api/roll/")
        assert resp.status_code == 200
        assert resp.json()["thread_id"] == thread_b.id

    async def test_inherited_plan_tag_excludes_candidate(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """A tag inherited from a containing reading plan filters the issue."""
        tag = await _create_private_tag(async_db, exclusion_user)
        _thread_a, issue_a = await _create_thread(
            async_db, exclusion_user, 1, "Alpha", 1
        )
        thread_b, _ = await _create_thread(async_db, exclusion_user, 2, "Beta", 2)
        assert issue_a is not None
        plan = await _create_plan_with_issue(async_db, exclusion_user, issue_a)
        await _assign_tag(async_db, tag, "ContinuityPlan", plan.id)
        await async_db.commit()

        await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        resp = await user_auth_client.post("/api/roll/")
        assert resp.status_code == 200
        assert resp.json()["thread_id"] == thread_b.id

    async def test_unrelated_tag_does_not_filter(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """Excluding a tag assigned nowhere keeps every candidate eligible."""
        tag = await _create_private_tag(async_db, exclusion_user, name="Unrelated")
        _thread_a, _ = await _create_thread(async_db, exclusion_user, 1, "Alpha", 1)
        _thread_b, _ = await _create_thread(async_db, exclusion_user, 2, "Beta", 2)
        await async_db.commit()

        await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        bootstrap = await user_auth_client.get("/api/v1/roll/bootstrap")
        assert bootstrap.status_code == 200
        assert bootstrap.json()["available_threads"] == 2

    async def test_bootstrap_reports_tag_excluded_threads(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """Bootstrap explains tag-excluded series and lists active exclusions."""
        tag = await _create_private_tag(async_db, exclusion_user)
        thread_a, issue_a = await _create_thread(
            async_db, exclusion_user, 1, "Alpha", 1
        )
        _thread_b, _ = await _create_thread(async_db, exclusion_user, 2, "Beta", 2)
        assert issue_a is not None
        await _assign_tag(async_db, tag, "Issue", issue_a.id)
        await async_db.commit()

        await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        resp = await user_auth_client.get("/api/v1/roll/bootstrap")
        assert resp.status_code == 200
        body = resp.json()
        assert [t["id"] for t in body["tag_exclusions"]] == [tag.id]
        tag_excluded = [
            entry
            for entry in body["excluded_threads"]
            if entry["reason"] == "tag_excluded"
        ]
        assert [entry["thread_id"] for entry in tag_excluded] == [thread_a.id]
        assert tag.name in tag_excluded[0]["detail"]
        pool_ids = [entry["id"] for entry in body["roll_pool"]]
        assert thread_a.id not in pool_ids

    async def test_empty_pool_explains_exclusions(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """An exclusion-emptied pool errors with the responsible exclusions."""
        tag = await _create_private_tag(async_db, exclusion_user)
        _thread_a, issue_a = await _create_thread(
            async_db, exclusion_user, 1, "Alpha", 1
        )
        assert issue_a is not None
        await _assign_tag(async_db, tag, "Issue", issue_a.id)
        await async_db.commit()

        await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        resp = await user_auth_client.post("/api/roll/")
        assert resp.status_code == 400
        assert tag.name in resp.json()["detail"]
        assert "exclusion" in resp.json()["detail"].lower()


class TestMidRollReroll:
    """Mid-roll exclusion auto-rerolls neutrally when pending is invalidated."""

    async def test_exclude_and_reroll_replaces_ineligible_pending(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """Excluding the pending issue's tag clears it and rolls another."""
        tag = await _create_private_tag(async_db, exclusion_user)
        thread_a, issue_a = await _create_thread(
            async_db, exclusion_user, 1, "Alpha", 1
        )
        thread_b, _ = await _create_thread(async_db, exclusion_user, 2, "Beta", 2)
        thread_c, _ = await _create_thread(async_db, exclusion_user, 3, "Gamma", 3)
        assert issue_a is not None
        await _assign_tag(async_db, tag, "Issue", issue_a.id)
        await async_db.commit()

        override = await user_auth_client.post(
            "/api/roll/override", json={"thread_id": thread_a.id}
        )
        assert override.status_code == 200

        session_before = await _get_session(async_db, exclusion_user)
        assert session_before is not None
        snoozed_before = list(session_before.snoozed_thread_ids or [])
        skipped_before = list(session_before.skipped_thread_ids or [])
        bandwidth_before = session_before.active_bandwidth
        bandwidth_source_before = session_before.bandwidth_source
        taste_before = await async_db.execute(
            select(func.count()).select_from(TasteSignal)
        )
        taste_count_before = taste_before.scalar()
        events_before = await async_db.execute(
            select(Event.type, func.count(Event.id))
            .where(Event.session_id == session_before.id)
            .group_by(Event.type)
        )
        event_counts_before = dict(events_before.all())
        positions_before = {
            thread.id: thread.queue_position
            for thread in (thread_a, thread_b, thread_c)
        }

        resp = await user_auth_client.post(
            f"/api/v1/roll/tag-exclusions/{tag.id}/exclude-and-reroll/"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["excluded_tag"]["id"] == tag.id
        assert body["pending_invalidated"] is True
        assert body["roll"] is not None
        assert body["roll"]["thread_id"] in {thread_b.id, thread_c.id}

        session_after = await _get_session(async_db, exclusion_user)
        assert session_after is not None
        assert session_after.pending_thread_id == body["roll"]["thread_id"]
        # Neutral: no snooze/skip entries, no bandwidth correction, no die move.
        assert list(session_after.snoozed_thread_ids or []) == snoozed_before
        assert list(session_after.skipped_thread_ids or []) == skipped_before
        assert session_after.active_bandwidth == bandwidth_before
        assert session_after.bandwidth_source == bandwidth_source_before
        assert session_after.manual_die == session_before.manual_die
        assert session_after.start_die == session_before.start_die
        # Neutral: queue positions untouched.
        positions_after = await async_db.execute(
            select(Thread.id, Thread.queue_position).where(
                Thread.user_id == exclusion_user.id
            )
        )
        assert dict(positions_after.all()) == positions_before
        # Neutral: exactly one new roll event, no snooze, no taste writes.
        events_after = await async_db.execute(
            select(Event.type, func.count(Event.id))
            .where(Event.session_id == session_after.id)
            .group_by(Event.type)
        )
        event_counts_after = dict(events_after.all())
        assert event_counts_after.get("roll", 0) == event_counts_before.get("roll", 0) + 1
        assert "snooze" not in event_counts_after
        taste_after = await async_db.execute(
            select(func.count()).select_from(TasteSignal)
        )
        assert taste_after.scalar() == taste_count_before

    async def test_exclude_and_reroll_keeps_eligible_pending(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """Excluding another thread's tag leaves the pending roll untouched."""
        tag = await _create_private_tag(async_db, exclusion_user)
        thread_a, _ = await _create_thread(async_db, exclusion_user, 1, "Alpha", 1)
        thread_b, issue_b = await _create_thread(
            async_db, exclusion_user, 2, "Beta", 2
        )
        assert issue_b is not None
        await _assign_tag(async_db, tag, "Issue", issue_b.id)
        await async_db.commit()

        override = await user_auth_client.post(
            "/api/roll/override", json={"thread_id": thread_a.id}
        )
        assert override.status_code == 200

        resp = await user_auth_client.post(
            f"/api/v1/roll/tag-exclusions/{tag.id}/exclude-and-reroll/"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["pending_invalidated"] is False
        assert body["roll"] is None

        session = await _get_session(async_db, exclusion_user)
        assert session is not None
        assert session.pending_thread_id == thread_a.id

    async def test_exclude_and_reroll_without_pending(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """Exclusion without a pending roll only persists the exclusion."""
        tag = await _create_private_tag(async_db, exclusion_user)
        await _create_thread(async_db, exclusion_user, 1, "Alpha", 1)
        await async_db.commit()

        resp = await user_auth_client.post(
            f"/api/v1/roll/tag-exclusions/{tag.id}/exclude-and-reroll/"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["pending_invalidated"] is False
        assert body["roll"] is None

        list_resp = await user_auth_client.get("/api/v1/roll/tag-exclusions/")
        assert [t["id"] for t in list_resp.json()["excluded_tags"]] == [tag.id]

    async def test_exclude_and_reroll_empty_pool_errors(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """Invalidating the only candidate explains the empty pool."""
        tag = await _create_private_tag(async_db, exclusion_user)
        thread_a, issue_a = await _create_thread(
            async_db, exclusion_user, 1, "Alpha", 1
        )
        assert issue_a is not None
        await _assign_tag(async_db, tag, "Issue", issue_a.id)
        await async_db.commit()

        override = await user_auth_client.post(
            "/api/roll/override", json={"thread_id": thread_a.id}
        )
        assert override.status_code == 200

        resp = await user_auth_client.post(
            f"/api/v1/roll/tag-exclusions/{tag.id}/exclude-and-reroll/"
        )
        assert resp.status_code == 400
        assert tag.name in resp.json()["detail"]


class TestUserScoping:
    """Private exclusions stay user-scoped; global tags exclude per user."""

    async def test_private_exclusion_does_not_affect_other_user(
        self,
        user_auth_client: AsyncClient,
        other_auth_client: AsyncClient,
        exclusion_user: User,
        other_user: User,
        async_db: AsyncSession,
    ) -> None:
        """One user's private exclusion never filters another user's pool."""
        tag = await _create_private_tag(async_db, exclusion_user)
        thread_a, issue_a = await _create_thread(
            async_db, exclusion_user, 1, "Alpha", 1
        )
        assert issue_a is not None
        await _assign_tag(async_db, tag, "Issue", issue_a.id)
        other_thread, _ = await _create_thread(async_db, other_user, 2, "Other", 1)
        await async_db.commit()

        await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )

        other_list = await other_auth_client.get("/api/v1/roll/tag-exclusions/")
        assert other_list.status_code == 200
        assert other_list.json()["excluded_tags"] == []

        other_roll = await other_auth_client.post("/api/roll/")
        assert other_roll.status_code == 200
        assert other_roll.json()["thread_id"] == other_thread.id

        # The other user cannot remove an exclusion they do not hold.
        del_resp = await other_auth_client.delete(
            f"/api/v1/roll/tag-exclusions/{tag.id}/"
        )
        assert del_resp.status_code == 404

    async def test_other_users_private_tag_is_invisible(
        self,
        other_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """Excluding another user's private tag reports not found, not forbidden."""
        tag = await _create_private_tag(async_db, exclusion_user)
        await async_db.commit()

        resp = await other_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        assert resp.status_code == 404

    async def test_global_tag_exclusion_is_per_user(
        self,
        user_auth_client: AsyncClient,
        other_auth_client: AsyncClient,
        exclusion_user: User,
        other_user: User,
        async_db: AsyncSession,
    ) -> None:
        """Excluding a global tag hides matches only for the excluding user."""
        tag = await _create_global_tag(async_db)
        thread_a, issue_a = await _create_thread(
            async_db, exclusion_user, 1, "Alpha", 1
        )
        assert issue_a is not None
        await _assign_tag(async_db, tag, "Issue", issue_a.id)
        other_thread, other_issue = await _create_thread(
            async_db, other_user, 2, "Other", 1
        )
        assert other_issue is not None
        await _assign_tag(async_db, tag, "Issue", other_issue.id)
        await async_db.commit()

        add_resp = await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        assert add_resp.status_code == 200

        user_roll = await user_auth_client.post("/api/roll/")
        assert user_roll.status_code == 400

        other_roll = await other_auth_client.post("/api/roll/")
        assert other_roll.status_code == 200
        assert other_roll.json()["thread_id"] == other_thread.id


class TestDeletionIntegration:
    """Tag deletion cleans up exclusion references with usage preview."""

    async def test_usage_previews_exclusion_reference(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """Usage reports the roll-exclusion consumer reference before deletion."""
        tag = await _create_private_tag(async_db, exclusion_user)
        await async_db.commit()

        await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        usage = await user_auth_client.get(f"/api/v1/tags/{tag.id}/usage/")
        assert usage.status_code == 200
        assert usage.json()["references_removed_by_consumers"] == {
            "roll_tag_exclusions": 1
        }

    async def test_delete_tag_removes_exclusions(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """Deleting a tag removes its exclusions and reports the cleanup."""
        tag = await _create_private_tag(async_db, exclusion_user)
        await async_db.commit()

        await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        delete_resp = await user_auth_client.delete(f"/api/v1/tags/{tag.id}/")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["references_removed_by_consumers"] == {
            "roll_tag_exclusions": 1
        }

        list_resp = await user_auth_client.get("/api/v1/roll/tag-exclusions/")
        assert list_resp.json()["excluded_tags"] == []


class TestBulkEligibility:
    """Bulk effective-tag resolution covers many candidates at once."""

    async def test_partition_helper_splits_pool_without_queries(
        self, exclusion_user: User, async_db: AsyncSession
    ) -> None:
        """The pure partition helper separates eligible and excluded rows."""
        thread_a, issue_a = await _create_thread(
            async_db, exclusion_user, 1, "Alpha", 1
        )
        thread_b, _ = await _create_thread(async_db, exclusion_user, 2, "Beta", 2)
        assert issue_a is not None
        tag = await _create_private_tag(async_db, exclusion_user)
        await _assign_tag(async_db, tag, "Thread", thread_a.id)
        await async_db.commit()

        service = RollTagExclusionService(async_db)
        state = await service.get_pool_exclusion_state(
            exclusion_user,
            [(thread_a.id, issue_a.id), (thread_b.id, None)],
        )
        assert [t.id for t in state.excluded_tags] == []
        assert state.ineligible_tag_ids == {}

        await service.add_exclusion(exclusion_user, tag.id)
        state = await service.get_pool_exclusion_state(
            exclusion_user,
            [(thread_a.id, issue_a.id), (thread_b.id, None)],
        )
        assert state.ineligible_tag_ids == {thread_a.id: [tag.id]}

        rows = [(thread_a, 1, "1"), (thread_b, 1, "1")]
        effective = {thread_a.id: {tag.id}, thread_b.id: set()}
        eligible, ineligible = partition_pool_by_tag_exclusions(
            rows, [tag.id], effective
        )
        assert [row[0].id for row in eligible] == [thread_b.id]
        assert ineligible == {thread_a.id: [tag.id]}

    async def test_snooze_and_skip_behavior_unchanged(
        self,
        user_auth_client: AsyncClient,
        exclusion_user: User,
        async_db: AsyncSession,
    ) -> None:
        """Ordinary snooze/skip flows work alongside tag exclusions."""
        tag = await _create_private_tag(async_db, exclusion_user, name="Unrelated")
        thread_a, _ = await _create_thread(async_db, exclusion_user, 1, "Alpha", 1)
        thread_b, _ = await _create_thread(async_db, exclusion_user, 2, "Beta", 2)
        await async_db.commit()

        await user_auth_client.post(
            "/api/v1/roll/tag-exclusions/", json={"tag_id": tag.id}
        )
        roll_resp = await user_auth_client.post("/api/roll/")
        assert roll_resp.status_code == 200
        first_id = roll_resp.json()["thread_id"]
        assert first_id in {thread_a.id, thread_b.id}

        skip_resp = await user_auth_client.post("/api/roll/skip")
        assert skip_resp.status_code == 200
        assert skip_resp.json()["thread_id"] != first_id
