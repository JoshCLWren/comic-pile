"""Tests for the polymorphic global/private tag system.

Covers the full closure-critical contract for issue #3030:
- global vs user-private tag scoping and admin governance
- polymorphic assignments (Issue, Thread, ContinuityPlan)
- privacy isolation across users
- normalized duplicate prevention and near-match suggestions
- the fixed 32-color palette with red default
- assignment integrity, target existence/ownership validation
- deletion cascades and usage reporting
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.auth import create_access_token
from tests.conftest import _create_async_db_override
from app.constants.tags import TAG_COLOR_NAMES, TAG_COLOR_PALETTE
from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
from app.database import get_db
from app.main import app
from app.models import ContinuityPlan, Issue, Tag, TagAssignment, Thread, User
from app.services.tag_service import TagDeletionHook, TagService, register_tag_deletion_hook


@pytest.fixture(autouse=True)
def enable_test_environment() -> Iterator[None]:
    """Enable test environment for all tests in this module."""
    import os
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


def _default_test_username() -> str:
    return f"tag_test_user_{__import__('os').getpid()}"


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
async def async_db(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Create an async test session isolated per test."""
    async with db_engine.connect() as connection:
        async with connection.begin():
            session = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()


@pytest_asyncio.fixture(scope="function")
async def admin_user(async_db: AsyncSession) -> AsyncIterator[User]:
    """Create an administrator test user."""
    now = datetime.now(UTC)
    user = User(id=2, username="admin_tag_test", is_admin=True, created_at=now)
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)
    await _sync_id_sequence(async_db, "users")
    yield user


@pytest_asyncio.fixture(scope="function")
async def non_admin_user(async_db: AsyncSession) -> AsyncIterator[User]:
    """Create a non-administrator test user."""
    now = datetime.now(UTC)
    user = User(id=3, username="user_tag_test", created_at=now)
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)
    await _sync_id_sequence(async_db, "users")
    yield user


@pytest_asyncio.fixture(scope="function")
async def admin_auth_client(db_engine: AsyncEngine, admin_user: User) -> AsyncIterator[AsyncClient]:
    """Authenticated admin client for API integration tests."""
    app.dependency_overrides[get_db] = await _create_async_db_override()

    transport = ASGITransport(app=app)
    ac = AsyncClient(transport=transport, base_url="http://test")
    csrf_token = generate_csrf_token()
    ac.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    ac.headers.update({CSRF_HEADER_NAME: csrf_token})
    token = create_access_token(data={"sub": admin_user.username, "jti": "test"})
    ac.headers.update({"Authorization": f"Bearer {token}"})
    try:
        yield ac
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def user_auth_client(db_engine: AsyncEngine, non_admin_user: User) -> AsyncIterator[AsyncClient]:
    """Authenticated non-admin client for API integration tests."""
    app.dependency_overrides[get_db] = await _create_async_db_override()

    transport = ASGITransport(app=app)
    ac = AsyncClient(transport=transport, base_url="http://test")
    csrf_token = generate_csrf_token()
    ac.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    ac.headers.update({CSRF_HEADER_NAME: csrf_token})
    token = create_access_token(data={"sub": non_admin_user.username, "jti": "test"})
    ac.headers.update({"Authorization": f"Bearer {token}"})
    try:
        yield ac
    finally:
        app.dependency_overrides.clear()


async def _create_target_entities(db: AsyncSession, owner: User) -> tuple[Thread, Issue, ContinuityPlan]:
    """Create a thread, its issue, and a continuity plan owned by the user."""
    now = datetime.now(UTC)
    thread = Thread(
        id=1, title="Batman", format="Comic", issues_remaining=10,
        queue_position=1, status="active", user_id=owner.id, created_at=now,
    )
    db.add(thread)
    await db.flush()
    issue = Issue(id=1, thread_id=thread.id, issue_number="1", position=1,
                  status="unread", created_at=now)
    db.add(issue)
    plan = ContinuityPlan(
        id=1, user_id=owner.id, name="My Plan", ordering_mode="informational",
        nodes_json=[], lanes_json=[], created_at=now, updated_at=now,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(thread)
    await db.refresh(issue)
    await db.refresh(plan)
    return thread, issue, plan


class TestPalette:
    """Tests for the fixed 32-color palette."""

    def test_palette_has_exactly_32_colors(self) -> None:
        assert len(TAG_COLOR_PALETTE) == 32
        assert len(TAG_COLOR_NAMES) == 32

    def test_red_is_default_color(self) -> None:
        from app.constants.tags import DEFAULT_TAG_COLOR_NAME, DEFAULT_TAG_COLOR_HEX
        assert DEFAULT_TAG_COLOR_NAME == "red"
        assert DEFAULT_TAG_COLOR_HEX == "#DC2626"
        assert TAG_COLOR_PALETTE["red"] == "#DC2626"

    def test_all_color_values_are_valid_hex(self) -> None:
        import re
        hex_re = re.compile(r"^#[0-9A-Fa-f]{6}$")
        for name, hex_value in TAG_COLOR_PALETTE.items():
            assert hex_re.match(hex_value), f"{name} has invalid hex {hex_value}"


class TestModelNormalization:
    """Tests for tag name normalization and casing."""

    async def test_name_casing_is_preserved_on_storage(self, admin_user, async_db) -> None:
        from app.constants.tags import validate_tag_color

        tag = Tag(
            id=1, name="X-Men Legends", normalized_name="x-men legends",
            scope="global", owner_user_id=None, color=validate_tag_color("red")[1],
        )
        async_db.add(tag)
        await async_db.commit()
        await async_db.refresh(tag)
        assert tag.name == "X-Men Legends"
        assert tag.normalized_name == "x-men legends"

    async def test_matching_is_case_insensitive(self, admin_user, async_db) -> None:
        from app.constants.tags import validate_tag_color
        from app.repositories import tag_repository

        await tag_repository.create_tag(
            async_db,
            Tag(id=1, name="Avengers", normalized_name="avengers", scope="global",
                owner_user_id=None, color=validate_tag_color("blue")[1]),
        )
        result = await tag_repository.get_tag_by_name(async_db, "AVENGERS", "global")
        assert result is not None
        assert result.name == "Avengers"
        result = await tag_repository.get_tag_by_name(async_db, "Avengers ", "global")
        assert result is not None

    async def test_whitespace_is_trimmed_on_matching(self, admin_user, async_db) -> None:
        from app.constants.tags import validate_tag_color
        from app.repositories import tag_repository

        await tag_repository.create_tag(
            async_db,
            Tag(id=1, name="Joker", normalized_name="joker", scope="global",
                owner_user_id=None, color=validate_tag_color("purple")[1]),
        )
        result = await tag_repository.get_tag_by_name(async_db, "  Joker  ", "global")
        assert result is not None
        assert result.name == "Joker"


class TestGlobalAndPrivateScoping:
    """Tests for global vs user-private tag scoping."""

    async def test_admin_can_create_global_tag(self, admin_user, async_db) -> None:
        service = TagService(async_db)
        tag = await service.create_tag(admin_user, "Global Tag", color="red", scope="global")
        assert tag.scope == "global"
        assert tag.owner_user_id is None
        assert tag.color == "#DC2626"

    async def test_non_admin_cannot_request_global_scope(self, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        with pytest.raises(Exception) as exc_info:
            await service.create_tag(non_admin_user, "Bad", color="red", scope="global")
        assert "administrator" in str(exc_info.value).lower()

    async def test_non_admin_creates_private_tag(self, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        tag = await service.create_tag(non_admin_user, "My Private Tag")
        assert tag.scope == "private"
        assert tag.owner_user_id == non_admin_user.id
        assert tag.color == "#DC2626"

    async def test_global_tag_visible_to_non_admin(self, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        global_tag = await service.create_tag(
            await admin_user, "Visible Global", color="green", scope="global"
        )
        tags = await service.list_tags(non_admin_user)
        tag_ids = {t.id for t in tags}
        assert global_tag.id in tag_ids

    async def test_private_tag_not_visible_across_users(self, admin_user, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        my_tag = await service.create_tag(non_admin_user, "Secret Tag")
        other_tags = await service.list_tags(admin_user)
        other_ids = {t.id for t in other_tags}
        assert my_tag.id not in other_ids

    async def test_private_tag_detail_returns_404_to_other_users(self, non_admin_user, admin_user, async_db) -> None:
        service = TagService(async_db)
        my_tag = await service.create_tag(non_admin_user, "Secret")
        with pytest.raises(Exception) as exc_info:
            await service.get_tag(admin_user, my_tag.id)
        assert "does not exist" in str(exc_info.value).lower()


class TestDuplicatePrevention:
    """Tests for normalized duplicate prevention."""

    async def test_exact_global_name_match_redirects_on_private_create(
        self, admin_user, non_admin_user, async_db
    ) -> None:
        service = TagService(async_db)
        global_tag = await service.create_tag(admin_user, "Red Label", color="red", scope="global")
        result = await service.create_tag(non_admin_user, "  red label  ", color="blue")
        assert result.redirected_to_global is True
        assert result.tag.id == global_tag.id
        assert result.tag.scope == "global"
        # No private duplicate was created
        count = await async_db.execute(
            select(func.count()).select_from(Tag).where(Tag.normalized_name == "red label")
        )
        assert count.scalar_one() == 1

    async def test_partial_near_name_allows_private_creation(self, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        await service.create_tag(await admin_user, "Avengers", color="red", scope="global")
        result = await service.create_tag(non_admin_user, "Avengers Assemble", color="blue")
        assert result.redirected_to_global is False
        assert result.tag.scope == "private"
        assert result.tag.name == "Avengers Assemble"

    async def test_same_private_name_allowed_for_different_users(self, admin_user, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        tag_a = await service.create_tag(non_admin_user, "My Tag")
        tag_b = await service.create_tag(admin_user, "My Tag")
        assert tag_a.id != tag_b.id
        assert tag_a.owner_user_id == non_admin_user.id
        assert tag_b.owner_user_id == admin_user.id

    async def test_same_private_name_denied_for_same_user(self, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        _tag_a = await service.create_tag(non_admin_user, "Same Name")
        with pytest.raises(Exception) as exc_info:
            await service.create_tag(non_admin_user, "same name ", color="blue")
        assert "unique" in str(exc_info.value).lower() or "constraint" in str(exc_info.value).lower()

    async def test_rename_private_to_global_name_is_refused(self, non_admin_user, admin_user, async_db) -> None:
        service = TagService(async_db)
        _global_tag = await service.create_tag(admin_user, "Global Name", color="red", scope="global")
        my_tag = await service.create_tag(non_admin_user, "Private Copy")
        with pytest.raises(Exception) as exc_info:
            await service.update_tag(non_admin_user, my_tag.id, name="global name")
        assert "global" in str(exc_info.value).lower()


class TestNearMatch:
    """Tests for fuzzy near-match detection."""

    async def test_near_match_by_edit_distance(self, admin_user, async_db) -> None:
        service = TagService(async_db)
        await service.create_tag(admin_user, "Spider-Man", color="red", scope="global")
        near = await service.near_match_tags(admin_user, "spider-man 2")
        names = [t.name for t in near]
        assert "Spider-Man" in names

    async def test_near_match_by_substring(self, admin_user, async_db) -> None:
        service = TagService(async_db)
        await service.create_tag(admin_user, "Justice League", color="blue", scope="global")
        near = await service.near_match_tags(admin_user, "justice")
        assert any(t.name == "Justice League" for t in near)

    async def test_near_match_not_created_as_assignment(self, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        await service.create_tag(await admin_user, "Batwoman", color="red", scope="global")
        result = await service.create_tag(non_admin_user, "batwoman", include_near_matches=True)
        assert result.redirected_to_global is True
        assert len(result.near_matches) == 0


class TestColorValidation:
    """Tests for strict 32-color palette validation."""

    async def test_valid_palette_name_accepted(self, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        tag = await service.create_tag(non_admin_user, "Test", color="cyan")
        assert tag.color == "#06B6D4"

    async def test_valid_hex_accepted(self, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        tag = await service.create_tag(non_admin_user, "Test", color="#3B82F6")
        assert tag.color == "#3B82F6"

    async def test_case_insensitive_palette_name(self, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        tag = await service.create_tag(non_admin_user, "Test", color="Cyan")
        assert tag.color == "#06B6D4"

    async def test_invalid_color_rejected(self, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        with pytest.raises(Exception) as exc_info:
            await service.create_tag(non_admin_user, "Test", color="#999999")
        assert "palette" in str(exc_info.value).lower()

    async def test_non_string_color_rejected(self, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        with pytest.raises(Exception) as exc_info:
            await service.create_tag(non_admin_user, "Test", color=123)
        assert "string" in str(exc_info.value).lower()


class TestPolymorphicAssignments:
    """Tests for polymorphic tag assignments to Issue, Thread, ContinuityPlan."""

    async def test_assign_to_issue(self, admin_user, async_db) -> None:
        thread, issue, _ = await _create_target_entities(async_db, admin_user)
        tag = await TagService(async_db).create_tag(admin_user, "Assign Test", color="red", scope="global")
        assignment = await TagService(async_db).assign_tag(admin_user, tag.id, "Issue", issue.id)
        assert assignment.target_type == "Issue"
        assert assignment.target_id == issue.id
        count = await async_db.execute(
            select(func.count()).select_from(TagAssignment).where(TagAssignment.tag_id == tag.id)
        )
        assert count.scalar_one() == 1

    async def test_assign_to_thread(self, admin_user, async_db) -> None:
        thread, _, _ = await _create_target_entities(async_db, admin_user)
        tag = await TagService(async_db).create_tag(admin_user, "Assign Test", color="red", scope="global")
        assignment = await TagService(async_db).assign_tag(admin_user, tag.id, "Thread", thread.id)
        assert assignment.target_type == "Thread"
        assert assignment.target_id == thread.id

    async def test_assign_to_continuity_plan(self, admin_user, async_db) -> None:
        _, _, plan = await _create_target_entities(async_db, admin_user)
        tag = await TagService(async_db).create_tag(admin_user, "Assign Test", color="red", scope="global")
        assignment = await TagService(async_db).assign_tag(admin_user, tag.id, "ContinuityPlan", plan.id)
        assert assignment.target_type == "ContinuityPlan"
        assert assignment.target_id == plan.id

    async def test_nonexistent_target_rejected(self, admin_user, async_db) -> None:
        tag = await TagService(async_db).create_tag(admin_user, "Test", color="red", scope="global")
        with pytest.raises(Exception) as exc_info:
            await TagService(async_db).assign_tag(admin_user, tag.id, "Thread", 99999)
        assert "does not exist" in str(exc_info.value).lower()

    async def test_unsupported_target_type_rejected(self, admin_user, async_db) -> None:
        tag = await TagService(async_db).create_tag(admin_user, "Test", color="red", scope="global")
        with pytest.raises(Exception) as exc_info:
            await TagService(async_db).assign_tag(admin_user, tag.id, "FooBar", 1)
        assert "Unsupported target type" in str(exc_info.value)

    async def test_idempotent_assignment_returns_existing(self, admin_user, async_db) -> None:
        thread, issue, _ = await _create_target_entities(async_db, admin_user)
        tag = await TagService(async_db).create_tag(admin_user, "Test", color="red", scope="global")
        first = await TagService(async_db).assign_tag(admin_user, tag.id, "Issue", issue.id)
        second = await TagService(async_db).assign_tag(admin_user, tag.id, "Issue", issue.id)
        assert first.id == second.id
        count = await async_db.execute(
            select(func.count()).select_from(TagAssignment).where(TagAssignment.tag_id == tag.id)
        )
        assert count.scalar_one() == 1


class TestOwnershipValidation:
    """Tests for private-tag assignment ownership rules."""

    async def test_cannot_assign_private_tag_to_another_users_target(
        self, admin_user, non_admin_user, async_db
    ) -> None:
        thread_a, issue_a, _ = await _create_target_entities(async_db, admin_user)
        tag = await TagService(async_db).create_tag(non_admin_user, "Mine", color="red")
        with pytest.raises(Exception) as exc_info:
            await TagService(async_db).assign_tag(
                non_admin_user, tag.id, "Issue", issue_a.id
            )
        assert "own" in str(exc_info.value).lower()

    async def test_admin_can_assign_private_tag_across_users(
        self, admin_user, non_admin_user, async_db
    ) -> None:
        thread_a, issue_a, _ = await _create_target_entities(async_db, admin_user)
        tag = await TagService(async_db).create_tag(non_admin_user, "Mine", color="red")
        assignment = await TagService(async_db).assign_tag(
            admin_user, tag.id, "Issue", issue_a.id
        )
        assert assignment.target_id == issue_a.id

    async def test_can_only_assign_your_own_private_tag(
        self, admin_user, non_admin_user, async_db
    ) -> None:
        thread_a, issue_a, _ = await _create_target_entities(async_db, admin_user)
        other_tag = await TagService(async_db).create_tag(admin_user, "Others", color="red")
        with pytest.raises(Exception) as exc_info:
            await TagService(async_db).assign_tag(
                non_admin_user, other_tag.id, "Issue", issue_a.id
            )
        assert "own private" in str(exc_info.value).lower()


class TestGlobalAdminGovernance:
    """Tests that global tag mutations require is_admin."""

    async def test_non_admin_cannot_create_global(self, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        with pytest.raises(Exception) as exc_info:
            await service.create_tag(non_admin_user, "Bad", color="red", scope="global")
        assert "administrator" in str(exc_info.value).lower()

    async def test_non_admin_cannot_update_global(self, non_admin_user, admin_user, async_db) -> None:
        service = TagService(async_db)
        global_tag = await service.create_tag(admin_user, "Global", color="red", scope="global")
        with pytest.raises(Exception) as exc_info:
            await service.update_tag(non_admin_user, global_tag.id, color="blue")
        assert "administrator" in str(exc_info.value).lower()

    async def test_non_admin_cannot_delete_global(self, non_admin_user, admin_user, async_db) -> None:
        service = TagService(async_db)
        global_tag = await service.create_tag(admin_user, "Global", color="red", scope="global")
        with pytest.raises(Exception) as exc_info:
            await service.delete_tag(non_admin_user, global_tag.id)
        assert "administrator" in str(exc_info.value).lower()

    async def test_non_admin_cannot_assign_global(self, non_admin_user, admin_user, async_db) -> None:
        service = TagService(async_db)
        global_tag = await service.create_tag(admin_user, "Global", color="red", scope="global")
        thread, issue, _ = await _create_target_entities(async_db, non_admin_user)
        with pytest.raises(Exception) as exc_info:
            await service.assign_tag(non_admin_user, global_tag.id, "Issue", issue.id)
        assert "administrator" in str(exc_info.value).lower()

    async def test_non_admin_cannot_unassign_global(self, non_admin_user, admin_user, async_db) -> None:
        service = TagService(async_db)
        global_tag = await service.create_tag(admin_user, "Global", color="red", scope="global")
        thread, issue, _ = await _create_target_entities(async_db, non_admin_user)
        await service.assign_tag(admin_user, global_tag.id, "Issue", issue.id)
        with pytest.raises(Exception) as exc_info:
            await service.unassign_tag(non_admin_user, global_tag.id, "Issue", issue.id)
        assert "administrator" in str(exc_info.value).lower()


class TestPrivateTagCRUD:
    """Tests for private tag create/update/delete flows."""

    async def test_private_tag_update(self, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        tag = await service.create_tag(non_admin_user, "Old Name", color="red")
        updated = await service.update_tag(non_admin_user, tag.id, name="New Name", color="green")
        assert updated.name == "New Name"
        assert updated.normalized_name == "new name"
        assert updated.color == "#10B981"
        assert updated.updated_at >= tag.created_at

    async def test_private_tag_delete_cascades_assignments(self, non_admin_user, async_db) -> None:
        thread, issue, _ = await _create_target_entities(async_db, non_admin_user)
        service = TagService(async_db)
        tag = await service.create_tag(non_admin_user, "ToDelete", color="red")
        await service.assign_tag(non_admin_user, tag.id, "Issue", issue.id)
        await service.assign_tag(non_admin_user, tag.id, "Thread", thread.id)
        result = await service.delete_tag(non_admin_user, tag.id)
        assert result.assignments_removed == 2
        count = await async_db.execute(
            select(func.count()).select_from(TagAssignment).where(TagAssignment.tag_id == tag.id)
        )
        assert count.scalar_one() == 0
        stored = await async_db.get(Tag, tag.id)
        assert stored is None

    async def test_admin_can_delete_anyone_private_tag(self, admin_user, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        tag = await service.create_tag(non_admin_user, "Others Tag", color="red")
        await service.assign_tag(non_admin_user, tag.id, "Issue", 1)
        result = await service.delete_tag(admin_user, tag.id)
        assert result.assignments_removed == 1

    async def test_delete_nonexistent_tag_raises(self, non_admin_user, async_db) -> None:
        service = TagService(async_db)
        with pytest.raises(Exception) as exc_info:
            await service.delete_tag(non_admin_user, 99999)
        assert "does not exist" in str(exc_info.value).lower()

    async def test_unassign_removes_assignment(self, non_admin_user, async_db) -> None:
        thread, issue, _ = await _create_target_entities(async_db, non_admin_user)
        service = TagService(async_db)
        tag = await service.create_tag(non_admin_user, "Unassign Test", color="red")
        assignment = await service.assign_tag(non_admin_user, tag.id, "Issue", issue.id)
        removed = await service.unassign_tag(non_admin_user, tag.id, "Issue", issue.id)
        assert removed.id == assignment.id
        count = await async_db.execute(
            select(func.count()).select_from(TagAssignment).where(TagAssignment.tag_id == tag.id)
        )
        assert count.scalar_one() == 0

    async def test_unassign_missing_assignment_raises(self, non_admin_user, async_db) -> None:
        tag = await TagService(async_db).create_tag(non_admin_user, "Test", color="red")
        with pytest.raises(Exception) as exc_info:
            await TagService(async_db).unassign_tag(non_admin_user, tag.id, "Issue", 1)
        assert "not assigned" in str(exc_info.value).lower()


class TestUsageReporting:
    """Tests for tag usage counting."""

    async def test_count_assignments(self, admin_user, async_db) -> None:
        thread, issue, plan = await _create_target_entities(async_db, admin_user)
        service = TagService(async_db)
        tag = await service.create_tag(admin_user, "Count Test", color="red", scope="global")
        await service.assign_tag(admin_user, tag.id, "Issue", issue.id)
        await service.assign_tag(admin_user, tag.id, "Thread", thread.id)
        await service.assign_tag(admin_user, tag.id, "ContinuityPlan", plan.id)
        total = await service.count_assignments(tag.id)
        assert total == 3
        by_type = await service.count_assignments_by_target_type(tag.id)
        assert by_type["Issue"] == 1
        assert by_type["Thread"] == 1
        assert by_type["ContinuityPlan"] == 1


class TestDeletionHooks:
    """Tests for the tag deletion hook registry."""

    class FakeRollFilterHook(TagDeletionHook):
        """A fake roll-filter deletion hook for testing the hook registry."""

        def __init__(self, items: dict[int, set[int]]) -> None:
            self.items = items
            self.removed = 0

        async def cleanup_tag_references(self, db: AsyncSession, tag_id: int) -> int:
            self.removed = len(self.items.get(tag_id, set()))
            return self.removed

    def test_hook_is_run_on_tag_deletion(self, admin_user, async_db) -> None:
        service = TagService(async_db)
        hook = self.FakeRollFilterHook({99: {1, 2, 3}})
        register_tag_deletion_hook(hook)
        try:
            result = service.delete_tag(admin_user, 99)
            assert hook.removed == 3
            assert result.references_removed_by_consumers["FakeRollFilterHook"] == 3
        finally:
            _tag_deletion_hooks.remove(hook)


class TestAPILayer:
    """Integration tests hitting the actual API routes."""

    async def test_list_tags_returns_global_and_private(
        self, admin_auth_client, admin_user, async_db
    ) -> None:
        service = TagService(async_db)
        await service.create_tag(admin_user, "Global 1", color="red", scope="global")
        await service.create_tag(admin_user, "Admin Private", color="blue")

        resp = await admin_auth_client.get("/api/tags/")
        assert resp.status_code == 200
        data = resp.json()
        tag_names = {t["name"] for t in data["tags"]}
        assert "Global 1" in tag_names
        assert "Admin Private" in tag_names

    async def test_create_private_tag_via_api(self, user_auth_client, non_admin_user, async_db) -> None:
        resp = await user_auth_client.post("/api/tags/", json={"name": "API Tag", "color": "red"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["tag"]["name"] == "API Tag"
        assert data["tag"]["scope"] == "private"
        assert data["redirected_to_global"] is False

    async def test_create_global_tag_requires_admin(self, user_auth_client, async_db) -> None:
        resp = await user_auth_client.post("/api/tags/", json={"name": "Global", "color": "red", "scope": "global"})
        assert resp.status_code == 403

    async def test_assign_via_api(self, user_auth_client, non_admin_user, async_db) -> None:
        thread, issue, _ = await _create_target_entities(async_db, non_admin_user)
        tag_resp = await user_auth_client.post("/api/tags/", json={"name": "API Tag"})
        tag_id = tag_resp.json()["tag"]["id"]
        resp = await user_auth_client.post(
            f"/api/tags/{tag_id}/assign/",
            json={"target_type": "Issue", "target_id": issue.id}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_type"] == "Issue"
        assert data["target_id"] == issue.id

    async def test_delete_cascades_and_reports_usage(self, user_auth_client, non_admin_user, async_db) -> None:
        thread, issue, _ = await _create_target_entities(async_db, non_admin_user)
        tag_resp = await user_auth_client.post("/api/tags/", json={"name": "Cascade Test"})
        tag_id = tag_resp.json()["tag"]["id"]
        await user_auth_client.post(
            f"/api/tags/{tag_id}/assign/",
            json={"target_type": "Issue", "target_id": issue.id}
        )
        await user_auth_client.post(
            f"/api/tags/{tag_id}/assign/",
            json={"target_type": "Thread", "target_id": thread.id}
        )
        resp = await user_auth_client.delete(f"/api/tags/{tag_id}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["assignments_removed"] == 2
        assert data["references_removed_by_consumers"] == {}


class TestTagScopeEnum:
    """Tests validating the schema enum handling."""

    async def test_schema_scope_coercion(self, non_admin_user, async_db) -> None:
        from app.schemas.tags import TagScope
        assert TagScope.PRIVATE == "private"
        assert TagScope.GLOBAL == "global"

    async def test_schema_target_type_coercion(self, non_admin_user, async_db) -> None:
        from app.schemas.tags import TagTargetType
        assert TagTargetType.ISSUE == "Issue"
        assert TagTargetType.THREAD == "Thread"
        assert TagTargetType.CONTINUITY_PLAN == "ContinuityPlan"
