"""Tests for additive effective-tag inheritance.

Covers the full closure-critical contract for issue #3031:
- service/query returns direct + effective tags for issues, threads, plans
- issue effective tags union direct issue tags, thread tags, and tags from
  every Reading Plan containing the issue
- multiple Reading Plans contributing the same tag deduplicate correctly
- effective tags retain all contributing inheritance sources
- private inherited tags remain visible only to their owner
- global inherited tags are visible to all users
- no child-level negation/override mechanism is introduced
- API representation lets the UI navigate to each inheritance source
- effective-tag logic relies on #3037's once-per-plan invariant instead of
  duplicate-occurrence compatibility behavior
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
from app.database import get_db
from app.main import app
from app.models import ContinuityPlan, Issue, Thread, User
from app.models.reading_plan_membership import ReadingPlanIssue
from app.services.errors import NotFoundError
from app.services.tag_inheritance_service import TagInheritanceService
from app.services.tag_service import TagService
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
async def admin_user(async_db: AsyncSession) -> AsyncIterator[User]:
    """Create an administrator test user."""
    now = datetime.now(UTC)
    user = User(id=2, username="admin_inherit_test", is_admin=True, created_at=now)
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)
    await _sync_id_sequence(async_db, "users")
    yield user


@pytest_asyncio.fixture(scope="function")
async def owner_user(async_db: AsyncSession) -> AsyncIterator[User]:
    """Create the non-admin owner of the tagged objects."""
    now = datetime.now(UTC)
    user = User(id=3, username="owner_inherit_test", created_at=now)
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)
    await _sync_id_sequence(async_db, "users")
    yield user


@pytest_asyncio.fixture(scope="function")
async def other_user(async_db: AsyncSession) -> AsyncIterator[User]:
    """Create a second non-admin user for privacy tests."""
    now = datetime.now(UTC)
    user = User(id=4, username="other_inherit_test", created_at=now)
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)
    await _sync_id_sequence(async_db, "users")
    yield user


@pytest_asyncio.fixture(scope="function")
async def owner_auth_client(
    async_db: AsyncSession, owner_user: User
) -> AsyncIterator[AsyncClient]:
    """Authenticated owner client sharing the test session."""
    app.dependency_overrides[get_db] = await _create_async_db_override(async_db)

    transport = ASGITransport(app=app)
    ac = AsyncClient(transport=transport, base_url="http://test")
    csrf_token = generate_csrf_token()
    ac.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    ac.headers.update({CSRF_HEADER_NAME: csrf_token})
    token = create_access_token(data={"sub": owner_user.username, "jti": "test"})
    ac.headers.update({"Authorization": f"Bearer {token}"})
    try:
        yield ac
    finally:
        app.dependency_overrides.clear()


async def _create_thread_issue_plan(
    db: AsyncSession,
    owner: User,
    *,
    thread_id: int = 1,
    issue_id: int = 1,
    plan_id: int = 1,
    plan_name: str = "Mignolaverse",
) -> tuple[Thread, Issue, ContinuityPlan]:
    """Create a thread, one of its issues, and a plan containing that issue."""
    now = datetime.now(UTC)
    thread = Thread(
        id=thread_id,
        title="B.P.R.D.",
        format="Comic",
        issues_remaining=10,
        queue_position=thread_id,
        status="active",
        user_id=owner.id,
        created_at=now,
    )
    db.add(thread)
    await db.flush()
    issue = Issue(
        id=issue_id,
        thread_id=thread.id,
        issue_number="3",
        position=1,
        status="unread",
        created_at=now,
    )
    db.add(issue)
    await db.flush()
    plan = ContinuityPlan(
        id=plan_id,
        user_id=owner.id,
        name=plan_name,
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
            occurrence_id=f"occ-{plan.id}-{issue.id}",
            issue_id=issue.id,
            lane_id="main",
            display_position=1,
        )
    )
    await db.commit()
    await db.refresh(thread)
    await db.refresh(issue)
    await db.refresh(plan)
    return thread, issue, plan


async def _make_global(
    db: AsyncSession, admin: User, name: str, target_type: str, target_id: int
) -> None:
    """Create a global tag as admin and assign it to a target."""
    service = TagService(db)
    created = await service.create_tag(admin, name, color="red", scope="global")
    await service.assign_tag(admin, created.tag.id, target_type, target_id)


async def _make_private(
    db: AsyncSession, owner: User, name: str, target_type: str, target_id: int
) -> None:
    """Create a private tag as the owner and assign it to an owned target."""
    service = TagService(db)
    created = await service.create_tag(owner, name, color="blue", scope="private")
    await service.assign_tag(owner, created.tag.id, target_type, target_id)


class TestIssueEffectiveTags:
    """Issue effective tags union direct, thread, and plan tags."""

    async def test_union_of_direct_thread_and_plan_tags(
        self, async_db: AsyncSession, admin_user: User, owner_user: User
    ) -> None:
        """Horror from the plan plus Physical from the thread plus direct."""
        thread, issue, plan = await _create_thread_issue_plan(
            async_db, owner_user, plan_name="Mignolaverse"
        )
        await _make_global(async_db, admin_user, "Horror", "ContinuityPlan", plan.id)
        await _make_private(async_db, owner_user, "Physical", "Thread", thread.id)
        await _make_private(async_db, owner_user, "Mine", "Issue", issue.id)

        result = await TagInheritanceService(async_db).get_issue_effective_tags(
            owner_user, issue.id
        )

        assert result.target_type == "Issue"
        assert result.target_id == issue.id
        assert {tag.name for tag in result.direct_tags} == {"Mine"}
        by_name = {entry.tag.name: entry for entry in result.effective_tags}
        assert set(by_name) == {"Horror", "Physical", "Mine"}
        assert by_name["Mine"].direct is True
        assert by_name["Horror"].direct is False
        assert by_name["Physical"].direct is False
        assert [
            (source.target_type, source.target_id) for source in by_name["Horror"].sources
        ] == [("ContinuityPlan", plan.id)]
        assert [
            (source.target_type, source.target_id)
            for source in by_name["Physical"].sources
        ] == [("Thread", thread.id)]
        assert [
            (source.target_type, source.target_id) for source in by_name["Mine"].sources
        ] == [("Issue", issue.id)]

    async def test_multiple_plans_deduplicate_with_all_sources(
        self, async_db: AsyncSession, admin_user: User, owner_user: User
    ) -> None:
        """One tag from two plans and the thread appears once, thrice sourced."""
        thread, issue, first = await _create_thread_issue_plan(
            async_db, owner_user, plan_id=1, plan_name="Mignolaverse"
        )
        _, _, second = await _create_thread_issue_plan(
            async_db,
            owner_user,
            thread_id=2,
            issue_id=2,
            plan_id=2,
            plan_name="Second Plan",
        )
        # Move the second plan onto the first issue so both plans contain it.
        await async_db.execute(
            text(
                "UPDATE reading_plan_issues SET issue_id = :issue "
                "WHERE plan_id = :plan"
            ),
            {"issue": issue.id, "plan": second.id},
        )
        await async_db.commit()
        await _make_global(async_db, admin_user, "Shared", "Thread", thread.id)
        await _make_global(async_db, admin_user, "Shared", "ContinuityPlan", first.id)
        await _make_global(async_db, admin_user, "Shared", "ContinuityPlan", second.id)

        result = await TagInheritanceService(async_db).get_issue_effective_tags(
            owner_user, issue.id
        )

        assert [entry.tag.name for entry in result.effective_tags] == ["Shared"]
        entry = result.effective_tags[0]
        assert entry.direct is False
        assert sorted(
            (source.target_type, source.target_id) for source in entry.sources
        ) == [
            ("ContinuityPlan", first.id),
            ("ContinuityPlan", second.id),
            ("Thread", thread.id),
        ]

    async def test_direct_and_inherited_same_tag_dedupes(
        self, async_db: AsyncSession, admin_user: User, owner_user: User
    ) -> None:
        """A directly assigned tag that is also inherited stays additive."""
        thread, issue, _plan = await _create_thread_issue_plan(async_db, owner_user)
        service = TagService(async_db)
        created = await service.create_tag(
            admin_user, "Horror", color="red", scope="global"
        )
        await service.assign_tag(admin_user, created.tag.id, "Thread", thread.id)
        await service.assign_tag(admin_user, created.tag.id, "Issue", issue.id)

        result = await TagInheritanceService(async_db).get_issue_effective_tags(
            owner_user, issue.id
        )

        assert [entry.tag.name for entry in result.effective_tags] == ["Horror"]
        entry = result.effective_tags[0]
        # Direct assignment marks the tag direct but never suppresses the
        # inherited thread source: there is no negation mechanism.
        assert entry.direct is True
        assert sorted(
            (source.target_type, source.target_id) for source in entry.sources
        ) == [("Issue", issue.id), ("Thread", thread.id)]
        assert [tag.name for tag in result.direct_tags] == ["Horror"]

    async def test_no_negation_or_override_surface(self) -> None:
        """The inheritance service exposes reads only, never suppression."""
        forbidden = ("negat", "override", "exclu", "suppress", "mask", "block")
        names = [name for name in dir(TagInheritanceService) if not name.startswith("_")]
        assert names, "inheritance service must expose reader methods"
        assert all(
            not any(token in name.lower() for token in forbidden) for name in names
        )


class TestPrivacy:
    """Private inherited tags stay with their owner; globals travel."""

    async def test_global_inherited_tags_visible_to_owner(
        self, async_db: AsyncSession, admin_user: User, owner_user: User
    ) -> None:
        """Admin-assigned global tags appear in a non-admin's effective tags."""
        _thread, issue, plan = await _create_thread_issue_plan(async_db, owner_user)
        await _make_global(async_db, admin_user, "Horror", "ContinuityPlan", plan.id)

        result = await TagInheritanceService(async_db).get_issue_effective_tags(
            owner_user, issue.id
        )

        assert [entry.tag.name for entry in result.effective_tags] == ["Horror"]

    async def test_other_users_private_tags_and_plans_excluded(
        self,
        async_db: AsyncSession,
        admin_user: User,
        owner_user: User,
        other_user: User,
    ) -> None:
        """Another user's plan and private vocabulary never leak across users."""
        _thread, issue, _plan = await _create_thread_issue_plan(async_db, owner_user)
        now = datetime.now(UTC)
        foreign_plan = ContinuityPlan(
            id=99,
            user_id=other_user.id,
            name="Foreign Plan",
            ordering_mode="informational",
            nodes_json=[],
            lanes_json=[],
            created_at=now,
            updated_at=now,
        )
        async_db.add(foreign_plan)
        await async_db.flush()
        async_db.add(
            ReadingPlanIssue(
                plan_id=foreign_plan.id,
                occurrence_id="occ-foreign",
                issue_id=issue.id,
                lane_id="main",
                display_position=1,
            )
        )
        await async_db.commit()
        await _make_private(
            async_db, other_user, "Sneaky", "ContinuityPlan", foreign_plan.id
        )
        await _make_global(
            async_db, admin_user, "ForeignGlobal", "ContinuityPlan", foreign_plan.id
        )

        result = await TagInheritanceService(async_db).get_issue_effective_tags(
            owner_user, issue.id
        )

        assert result.effective_tags == []
        assert result.direct_tags == []

    async def test_unowned_targets_are_not_found(
        self,
        async_db: AsyncSession,
        owner_user: User,
        other_user: User,
    ) -> None:
        """Viewers cannot resolve effective tags for foreign objects."""
        thread, issue, plan = await _create_thread_issue_plan(async_db, owner_user)
        service = TagInheritanceService(async_db)

        with pytest.raises(NotFoundError):
            await service.get_issue_effective_tags(other_user, issue.id)
        with pytest.raises(NotFoundError):
            await service.get_thread_effective_tags(other_user, thread.id)
        with pytest.raises(NotFoundError):
            await service.get_plan_effective_tags(other_user, plan.id)


class TestThreadAndPlanEffectiveTags:
    """Threads and plans have no parents, so effective equals direct."""

    async def test_thread_effective_tags_are_direct_only(
        self, async_db: AsyncSession, admin_user: User, owner_user: User
    ) -> None:
        """Thread effective tags mirror its direct assignments."""
        thread, issue, plan = await _create_thread_issue_plan(async_db, owner_user)
        await _make_private(async_db, owner_user, "Physical", "Thread", thread.id)
        await _make_global(async_db, admin_user, "Horror", "ContinuityPlan", plan.id)
        await _make_private(async_db, owner_user, "Mine", "Issue", issue.id)

        result = await TagInheritanceService(async_db).get_thread_effective_tags(
            owner_user, thread.id
        )

        assert result.target_type == "Thread"
        assert [tag.name for tag in result.direct_tags] == ["Physical"]
        assert [entry.tag.name for entry in result.effective_tags] == ["Physical"]
        entry = result.effective_tags[0]
        assert entry.direct is True
        assert [(s.target_type, s.target_id) for s in entry.sources] == [
            ("Thread", thread.id)
        ]

    async def test_plan_effective_tags_are_direct_only(
        self, async_db: AsyncSession, admin_user: User, owner_user: User
    ) -> None:
        """Plan effective tags mirror its direct assignments."""
        thread, _issue, plan = await _create_thread_issue_plan(async_db, owner_user)
        await _make_global(async_db, admin_user, "Horror", "ContinuityPlan", plan.id)
        await _make_private(async_db, owner_user, "Physical", "Thread", thread.id)

        result = await TagInheritanceService(async_db).get_plan_effective_tags(
            owner_user, plan.id
        )

        assert result.target_type == "ContinuityPlan"
        assert [tag.name for tag in result.direct_tags] == ["Horror"]
        assert [entry.tag.name for entry in result.effective_tags] == ["Horror"]


class TestOncePerPlanInvariant:
    """Effective-tag logic relies on #3037 instead of occurrence dedup."""

    async def test_duplicate_membership_is_rejected_by_the_database(
        self, async_db: AsyncSession, owner_user: User
    ) -> None:
        """The uniqueness invariant holds, so inheritance needs no compat path."""
        _thread, issue, plan = await _create_thread_issue_plan(async_db, owner_user)
        async_db.add(
            ReadingPlanIssue(
                plan_id=plan.id,
                occurrence_id="occ-duplicate",
                issue_id=issue.id,
                lane_id="second-lane",
                display_position=9,
            )
        )
        with pytest.raises(IntegrityError):
            await async_db.flush()


class TestEffectiveTagsApi:
    """API representations expose navigable inheritance sources."""

    async def test_issue_effective_tags_api(
        self,
        async_db: AsyncSession,
        admin_user: User,
        owner_user: User,
        owner_auth_client: AsyncClient,
    ) -> None:
        """The issue endpoint returns direct tags and sourced effective tags."""
        thread, issue, plan = await _create_thread_issue_plan(
            async_db, owner_user, plan_name="Mignolaverse"
        )
        await _make_global(async_db, admin_user, "Horror", "ContinuityPlan", plan.id)
        await _make_private(async_db, owner_user, "Physical", "Thread", thread.id)
        await _make_private(async_db, owner_user, "Mine", "Issue", issue.id)

        response = await owner_auth_client.get(f"/api/v1/tags/effective/issue/{issue.id}/")

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["target_type"] == "Issue"
        assert payload["target_id"] == issue.id
        assert [tag["name"] for tag in payload["direct_tags"]] == ["Mine"]
        by_name = {entry["tag"]["name"]: entry for entry in payload["effective_tags"]}
        assert set(by_name) == {"Horror", "Physical", "Mine"}
        horror_sources = by_name["Horror"]["sources"]
        assert horror_sources == [
            {
                "target_type": "ContinuityPlan",
                "target_id": plan.id,
                "display_name": "Mignolaverse",
            }
        ]
        assert by_name["Physical"]["sources"][0]["target_type"] == "Thread"
        assert by_name["Physical"]["sources"][0]["target_id"] == thread.id

    async def test_thread_and_plan_effective_tags_api(
        self,
        async_db: AsyncSession,
        admin_user: User,
        owner_user: User,
        owner_auth_client: AsyncClient,
    ) -> None:
        """Thread and plan endpoints return their direct tags as effective."""
        thread, _issue, plan = await _create_thread_issue_plan(async_db, owner_user)
        await _make_private(async_db, owner_user, "Physical", "Thread", thread.id)
        await _make_global(async_db, admin_user, "Horror", "ContinuityPlan", plan.id)

        thread_response = await owner_auth_client.get(
            f"/api/v1/tags/effective/thread/{thread.id}/"
        )
        plan_response = await owner_auth_client.get(
            f"/api/v1/tags/effective/plan/{plan.id}/"
        )

        assert thread_response.status_code == 200, thread_response.text
        assert [t["name"] for t in thread_response.json()["direct_tags"]] == ["Physical"]
        assert plan_response.status_code == 200, plan_response.text
        assert [t["name"] for t in plan_response.json()["direct_tags"]] == ["Horror"]

    async def test_foreign_issue_effective_tags_api_is_not_found(
        self,
        async_db: AsyncSession,
        owner_user: User,
        owner_auth_client: AsyncClient,
        other_user: User,
    ) -> None:
        """Effective tags for another user's issue are not discoverable."""
        _thread, issue, _plan = await _create_thread_issue_plan(
            async_db, other_user, thread_id=7, issue_id=7, plan_id=7
        )

        response = await owner_auth_client.get(f"/api/v1/tags/effective/issue/{issue.id}/")

        assert response.status_code == 404
