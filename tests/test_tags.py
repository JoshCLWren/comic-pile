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

import os
import re
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.constants import (
    DEFAULT_TAG_COLOR_HEX,
    DEFAULT_TAG_COLOR_NAME,
    TAG_COLOR_NAMES,
    TAG_COLOR_PALETTE,
    TAG_TARGET_TYPES,
    validate_tag_color,
)
from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
from app.database import get_db
from app.main import app
from app.models import ContinuityPlan, Issue, Tag, TagAssignment, Thread, User
from app.repositories import tag_repository
from app.services.errors import (
    ConflictError,
    ForbiddenError,
    InvalidRequestError,
    NotFoundError,
)
from app.services.tag_service import (
    TagDeletionHook,
    TagService,
    purge_target_assignments,
    register_tag_deletion_hook,
    unregister_tag_deletion_hook,
)
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
async def admin_auth_client(async_db: AsyncSession, admin_user: User) -> AsyncIterator[AsyncClient]:
    """Authenticated admin client sharing the test session."""
    app.dependency_overrides[get_db] = await _create_async_db_override(async_db)

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
async def user_auth_client(async_db: AsyncSession, non_admin_user: User) -> AsyncIterator[AsyncClient]:
    """Authenticated non-admin client sharing the test session."""
    app.dependency_overrides[get_db] = await _create_async_db_override(async_db)

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


async def _create_target_entities(
    db: AsyncSession, owner: User
) -> tuple[Thread, Issue, ContinuityPlan]:
    """Create a thread, its issue, and a reading plan owned by the user."""
    now = datetime.now(UTC)
    thread = Thread(
        id=1,
        title="Batman",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=owner.id,
        created_at=now,
    )
    db.add(thread)
    await db.flush()
    issue = Issue(
        id=1,
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
        created_at=now,
    )
    db.add(issue)
    plan = ContinuityPlan(
        id=1,
        user_id=owner.id,
        name="My Plan",
        ordering_mode="informational",
        nodes_json=[],
        lanes_json=[],
        created_at=now,
        updated_at=now,
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
        """The palette and its name list both contain 32 entries."""
        assert len(TAG_COLOR_PALETTE) == 32
        assert len(TAG_COLOR_NAMES) == 32

    def test_red_is_default_color(self) -> None:
        """Red is the default tag color and maps to #DC2626."""
        assert DEFAULT_TAG_COLOR_NAME == "red"
        assert DEFAULT_TAG_COLOR_HEX == "#DC2626"
        assert TAG_COLOR_PALETTE["red"] == "#DC2626"

    def test_all_color_values_are_valid_hex(self) -> None:
        """Every palette entry is a valid #RRGGBB hex value."""
        hex_re = re.compile(r"^#[0-9A-Fa-f]{6}$")
        for name, hex_value in TAG_COLOR_PALETTE.items():
            assert hex_re.match(hex_value), f"{name} has invalid hex {hex_value}"


class TestModelNormalization:
    """Tests for tag name normalization and casing."""

    async def test_name_casing_is_preserved_on_storage(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """The stored display name keeps the requested casing."""
        tag = Tag(
            id=1,
            name="X-Men Legends",
            normalized_name="x-men legends",
            scope="global",
            owner_user_id=None,
            color=validate_tag_color("red")[1],
        )
        async_db.add(tag)
        await async_db.commit()
        await async_db.refresh(tag)
        assert tag.name == "X-Men Legends"
        assert tag.normalized_name == "x-men legends"

    async def test_matching_is_case_insensitive(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Name lookup succeeds regardless of input casing."""
        await tag_repository.create_tag(
            async_db,
            Tag(
                id=1,
                name="Avengers",
                normalized_name="avengers",
                scope="global",
                owner_user_id=None,
                color=validate_tag_color("red")[1],
            ),
        )
        result = await tag_repository.get_tag_by_name(async_db, "AVENGERS", "global")
        assert result is not None
        assert result.name == "Avengers"
        result = await tag_repository.get_tag_by_name(async_db, "Avengers ", "global")
        assert result is not None

    async def test_whitespace_is_trimmed_on_matching(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Name lookup trims surrounding whitespace before matching."""
        await tag_repository.create_tag(
            async_db,
            Tag(
                id=1,
                name="Joker",
                normalized_name="joker",
                scope="global",
                owner_user_id=None,
                color=validate_tag_color("red")[1],
            ),
        )
        result = await tag_repository.get_tag_by_name(async_db, "  Joker  ", "global")
        assert result is not None
        assert result.name == "Joker"


class TestGlobalAndPrivateScoping:
    """Tests for global vs user-private tag scoping."""

    async def test_admin_can_create_global_tag(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Admins can create global tags owned by nobody."""
        service = TagService(async_db)
        result = await service.create_tag(
            admin_user, "Global Tag", color="red", scope="global"
        )
        assert result.tag.scope == "global"
        assert result.tag.owner_user_id is None
        assert result.tag.color == "#DC2626"

    async def test_non_admin_cannot_request_global_scope(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Non-admin requests for global scope are refused."""
        service = TagService(async_db)
        with pytest.raises(ForbiddenError) as exc_info:
            await service.create_tag(
                non_admin_user, "Bad", color="red", scope="global"
            )
        assert "administrator" in str(exc_info.value).lower()

    async def test_non_admin_creates_private_tag(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Non-admin users create private tags owned by themselves."""
        service = TagService(async_db)
        result = await service.create_tag(non_admin_user, "My Private Tag")
        assert result.tag.scope == "private"
        assert result.tag.owner_user_id == non_admin_user.id
        assert result.tag.color == "#DC2626"

    async def test_global_tag_visible_to_non_admin(
        self, admin_user: User, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Global tags are listed for every authenticated user."""
        service = TagService(async_db)
        global_tag = await service.create_tag(
            admin_user, "Visible Global", color="green", scope="global"
        )
        tags = await service.list_tags(non_admin_user)
        tag_ids = {t.id for t in tags}
        assert global_tag.tag.id in tag_ids

    async def test_private_tag_not_visible_across_users(
        self, admin_user: User, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """One user's private tags never appear in another user's listing."""
        service = TagService(async_db)
        my_tag = await service.create_tag(non_admin_user, "Secret Tag")
        other_tags = await service.list_tags(admin_user)
        other_ids = {t.id for t in other_tags}
        assert my_tag.tag.id not in other_ids

    async def test_private_tag_detail_returns_404_to_other_users(
        self, non_admin_user: User, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Fetching another user's private tag reports it as missing.

        Administrators are not exempt: a private tag is visible only to its
        owner, so admin governance over global vocabulary must not become a
        window into anyone's private vocabulary.
        """
        service = TagService(async_db)
        my_tag = await service.create_tag(non_admin_user, "Secret")
        with pytest.raises(NotFoundError) as exc_info:
            await service.get_tag(admin_user, my_tag.tag.id)
        assert "does not exist" in str(exc_info.value).lower()


class TestDuplicatePrevention:
    """Tests for normalized duplicate prevention."""

    async def test_exact_global_name_match_redirects_on_private_create(
        self, admin_user: User, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """A private create matching a global name returns the global tag."""
        service = TagService(async_db)
        global_tag = await service.create_tag(
            admin_user, "Red Label", color="red", scope="global"
        )
        result = await service.create_tag(
            non_admin_user, "  red label  ", color="blue"
        )
        assert result.redirected_to_global is True
        assert result.tag.id == global_tag.tag.id
        assert result.tag.scope == "global"
        # No private duplicate was created
        count = await async_db.execute(
            select(func.count()).select_from(Tag).where(
                Tag.normalized_name == "red label"
            )
        )
        assert count.scalar_one() == 1

    async def test_partial_near_name_allows_private_creation(
        self, admin_user: User, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """A name that is only a near match still creates a private tag."""
        service = TagService(async_db)
        await service.create_tag(admin_user, "Avengers", color="red", scope="global")
        result = await service.create_tag(
            non_admin_user, "Avengers Assemble", color="blue"
        )
        assert result.redirected_to_global is False
        assert result.tag.scope == "private"
        assert result.tag.name == "Avengers Assemble"

    async def test_same_private_name_allowed_for_different_users(
        self, admin_user: User, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Different users may independently own identically named tags."""
        service = TagService(async_db)
        tag_a = await service.create_tag(non_admin_user, "My Tag")
        tag_b = await service.create_tag(admin_user, "My Tag")
        assert tag_a.tag.id != tag_b.tag.id
        assert tag_a.tag.owner_user_id == non_admin_user.id
        assert tag_b.tag.owner_user_id == admin_user.id

    async def test_same_private_name_denied_for_same_user(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """A second private tag with the same normalized name is refused."""
        service = TagService(async_db)
        _tag_a = await service.create_tag(non_admin_user, "Same Name")
        with pytest.raises(ConflictError) as exc_info:
            await service.create_tag(non_admin_user, "same name ", color="blue")
        assert "already exists" in str(exc_info.value).lower()

    async def test_rename_private_to_global_name_is_refused(
        self, non_admin_user: User, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Renaming a private tag to a global name is refused."""
        service = TagService(async_db)
        _global_tag = await service.create_tag(
            admin_user, "Global Name", color="red", scope="global"
        )
        my_tag = await service.create_tag(non_admin_user, "Private Copy")
        with pytest.raises(ConflictError) as exc_info:
            await service.update_tag(non_admin_user, my_tag.tag.id, name="global name")
        assert "global" in str(exc_info.value).lower()

    async def test_rename_private_to_duplicate_private_is_refused(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Renaming onto another of the same owner's names is a conflict."""
        service = TagService(async_db)
        await service.create_tag(non_admin_user, "First Private")
        second = await service.create_tag(non_admin_user, "Second Private")
        with pytest.raises(ConflictError) as exc_info:
            await service.update_tag(
                non_admin_user, second.tag.id, name="first private"
            )
        assert "already exists" in str(exc_info.value).lower()
        untouched = await async_db.get(Tag, second.tag.id)
        assert untouched is not None
        assert untouched.name == "Second Private"

    async def test_rename_private_to_another_users_name_is_allowed(
        self, non_admin_user: User, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Private vocabulary stays independent between different owners."""
        service = TagService(async_db)
        await service.create_tag(admin_user, "Shared Name")
        mine = await service.create_tag(non_admin_user, "My Copy")
        updated = await service.update_tag(non_admin_user, mine.tag.id, name="Shared Name")
        assert updated.normalized_name == "shared name"
        assert updated.owner_user_id == non_admin_user.id


class TestNearMatch:
    """Tests for fuzzy near-match detection."""

    async def test_near_match_by_edit_distance(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Names within the edit-distance threshold are suggested."""
        service = TagService(async_db)
        await service.create_tag(admin_user, "Spider-Man", color="red", scope="global")
        near = await service.near_match_tags(admin_user, "spider-man 2")
        names = [t.name for t in near]
        assert "Spider-Man" in names

    async def test_near_match_by_substring(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Substring relationships count as near matches."""
        service = TagService(async_db)
        await service.create_tag(
            admin_user, "Justice League", color="blue", scope="global"
        )
        near = await service.near_match_tags(admin_user, "justice")
        assert any(t.name == "Justice League" for t in near)

    async def test_near_match_not_created_as_assignment(
        self, admin_user: User, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """An exact global match redirects without near-match suggestions."""
        service = TagService(async_db)
        await service.create_tag(admin_user, "Batwoman", color="red", scope="global")
        result = await service.create_tag(
            non_admin_user, "batwoman", include_near_matches=True
        )
        assert result.redirected_to_global is True
        assert len(result.near_matches) == 0


class TestColorValidation:
    """Tests for strict 32-color palette validation."""

    async def test_valid_palette_name_accepted(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """A palette color name is accepted and stored as its hex value."""
        service = TagService(async_db)
        result = await service.create_tag(non_admin_user, "Test", color="cyan")
        assert result.tag.color == "#06B6D4"

    async def test_valid_hex_accepted(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """A palette hex value is accepted verbatim."""
        service = TagService(async_db)
        result = await service.create_tag(non_admin_user, "Test", color="#3B82F6")
        assert result.tag.color == "#3B82F6"

    async def test_case_insensitive_palette_name(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Palette color names match case-insensitively."""
        service = TagService(async_db)
        result = await service.create_tag(non_admin_user, "Test", color="Cyan")
        assert result.tag.color == "#06B6D4"

    async def test_invalid_color_rejected(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """A hex value outside the palette is refused."""
        service = TagService(async_db)
        with pytest.raises(InvalidRequestError) as exc_info:
            await service.create_tag(non_admin_user, "Test", color="#999999")
        assert "palette" in str(exc_info.value).lower()

    async def test_non_string_color_rejected(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """A non-string color value is refused."""
        service = TagService(async_db)
        with pytest.raises(InvalidRequestError) as exc_info:
            await service.create_tag(non_admin_user, "Test", color=123)
        assert "string" in str(exc_info.value).lower()


class TestPolymorphicAssignments:
    """Tests for polymorphic tag assignments to Issue, Thread, ContinuityPlan."""

    async def test_assign_to_issue(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """A tag can be attached to an issue."""
        _thread, issue, _plan = await _create_target_entities(async_db, admin_user)
        created = await TagService(async_db).create_tag(
            admin_user, "Assign Test", color="red", scope="global"
        )
        tag = created.tag
        assignment = await TagService(async_db).assign_tag(
            admin_user, tag.id, "Issue", issue.id
        )
        assert assignment.target_type == "Issue"
        assert assignment.target_id == issue.id
        count = await async_db.execute(
            select(func.count()).select_from(TagAssignment).where(
                TagAssignment.tag_id == tag.id
            )
        )
        assert count.scalar_one() == 1

    async def test_assign_to_thread(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """A tag can be attached to a thread."""
        thread, _issue, _plan = await _create_target_entities(async_db, admin_user)
        created = await TagService(async_db).create_tag(
            admin_user, "Assign Test", color="red", scope="global"
        )
        tag = created.tag
        assignment = await TagService(async_db).assign_tag(
            admin_user, tag.id, "Thread", thread.id
        )
        assert assignment.target_type == "Thread"
        assert assignment.target_id == thread.id

    async def test_assign_to_continuity_plan(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """A tag can be attached to a reading plan."""
        _thread, _issue, plan = await _create_target_entities(async_db, admin_user)
        created = await TagService(async_db).create_tag(
            admin_user, "Assign Test", color="red", scope="global"
        )
        tag = created.tag
        assignment = await TagService(async_db).assign_tag(
            admin_user, tag.id, "ContinuityPlan", plan.id
        )
        assert assignment.target_type == "ContinuityPlan"
        assert assignment.target_id == plan.id

    async def test_nonexistent_target_rejected(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Assigning to a missing target raises a not-found error."""
        created = await TagService(async_db).create_tag(
            admin_user, "Test", color="red", scope="global"
        )
        tag = created.tag
        with pytest.raises(NotFoundError) as exc_info:
            await TagService(async_db).assign_tag(admin_user, tag.id, "Thread", 99999)
        assert "does not exist" in str(exc_info.value).lower()

    async def test_unsupported_target_type_rejected(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Assigning to an unregistered target type is refused."""
        created = await TagService(async_db).create_tag(
            admin_user, "Test", color="red", scope="global"
        )
        tag = created.tag
        with pytest.raises(InvalidRequestError) as exc_info:
            await TagService(async_db).assign_tag(admin_user, tag.id, "FooBar", 1)
        assert "Unsupported target type" in str(exc_info.value)

    async def test_idempotent_assignment_returns_existing(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Assigning the same tag twice yields one assignment row."""
        _thread, issue, _plan = await _create_target_entities(async_db, admin_user)
        created = await TagService(async_db).create_tag(
            admin_user, "Test", color="red", scope="global"
        )
        tag = created.tag
        first = await TagService(async_db).assign_tag(
            admin_user, tag.id, "Issue", issue.id
        )
        second = await TagService(async_db).assign_tag(
            admin_user, tag.id, "Issue", issue.id
        )
        assert first.id == second.id
        count = await async_db.execute(
            select(func.count()).select_from(TagAssignment).where(
                TagAssignment.tag_id == tag.id
            )
        )
        assert count.scalar_one() == 1


class TestOwnershipValidation:
    """Tests for private-tag assignment ownership rules."""

    async def test_cannot_assign_private_tag_to_another_users_target(
        self, admin_user: User, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Private tags cannot be attached to targets owned by others."""
        _thread, issue_a, _plan = await _create_target_entities(async_db, admin_user)
        created = await TagService(async_db).create_tag(
            non_admin_user, "Mine", color="red"
        )
        tag = created.tag
        with pytest.raises(ForbiddenError) as exc_info:
            await TagService(async_db).assign_tag(
                non_admin_user, tag.id, "Issue", issue_a.id
            )
        assert "own" in str(exc_info.value).lower()

    async def test_admin_cannot_assign_another_users_private_tag(
        self, admin_user: User, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Admins may not push a user's private tag onto any target."""
        _thread, issue_a, _plan = await _create_target_entities(async_db, admin_user)
        created = await TagService(async_db).create_tag(
            non_admin_user, "Mine", color="red"
        )
        tag = created.tag
        with pytest.raises(ForbiddenError) as exc_info:
            await TagService(async_db).assign_tag(
                admin_user, tag.id, "Issue", issue_a.id
            )
        assert "own private" in str(exc_info.value).lower()

    async def test_admin_cannot_assign_private_tag_to_other_users_target(
        self, admin_user: User, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """An owner's own private tag never lands on another user's target."""
        _thread, issue_a, _plan = await _create_target_entities(async_db, non_admin_user)
        created = await TagService(async_db).create_tag(admin_user, "Mine", color="red")
        tag = created.tag
        with pytest.raises(ForbiddenError) as exc_info:
            await TagService(async_db).assign_tag(
                admin_user, tag.id, "Issue", issue_a.id
            )
        assert "targets you own" in str(exc_info.value).lower()

    async def test_admin_assigns_global_tag_to_other_users_target(
        self, admin_user: User, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Global tags remain assignable by admins to any existing target."""
        _thread, issue_a, _plan = await _create_target_entities(async_db, non_admin_user)
        created = await TagService(async_db).create_tag(
            admin_user, "Shared", color="red", scope="global"
        )
        assignment = await TagService(async_db).assign_tag(
            admin_user, created.tag.id, "Issue", issue_a.id
        )
        assert assignment.target_id == issue_a.id

    async def test_can_only_assign_your_own_private_tag(
        self, admin_user: User, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Users cannot assign a private tag owned by someone else."""
        _thread, issue_a, _plan = await _create_target_entities(async_db, admin_user)
        other_created = await TagService(async_db).create_tag(
            admin_user, "Others", color="red"
        )
        other_tag = other_created.tag
        with pytest.raises(ForbiddenError) as exc_info:
            await TagService(async_db).assign_tag(
                non_admin_user, other_tag.id, "Issue", issue_a.id
            )
        assert "own private" in str(exc_info.value).lower()


class TestGlobalAdminGovernance:
    """Tests that global tag mutations require is_admin."""

    async def test_non_admin_cannot_create_global(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Only admins can create global tags."""
        service = TagService(async_db)
        with pytest.raises(ForbiddenError) as exc_info:
            await service.create_tag(non_admin_user, "Bad", color="red", scope="global")
        assert "administrator" in str(exc_info.value).lower()

    async def test_non_admin_cannot_update_global(
        self, non_admin_user: User, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Only admins can edit global tags."""
        service = TagService(async_db)
        global_tag = await service.create_tag(
            admin_user, "Global", color="red", scope="global"
        )
        with pytest.raises(ForbiddenError) as exc_info:
            await service.update_tag(
                non_admin_user, global_tag.tag.id, color="blue"
            )
        assert "administrator" in str(exc_info.value).lower()

    async def test_non_admin_cannot_delete_global(
        self, non_admin_user: User, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Only admins can delete global tags."""
        service = TagService(async_db)
        global_tag = await service.create_tag(
            admin_user, "Global", color="red", scope="global"
        )
        with pytest.raises(ForbiddenError) as exc_info:
            await service.delete_tag(non_admin_user, global_tag.tag.id)
        assert "administrator" in str(exc_info.value).lower()

    async def test_non_admin_cannot_assign_global(
        self, non_admin_user: User, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Only admins can assign global tags."""
        service = TagService(async_db)
        global_tag = await service.create_tag(
            admin_user, "Global", color="red", scope="global"
        )
        _thread, issue, _plan = await _create_target_entities(async_db, non_admin_user)
        with pytest.raises(ForbiddenError) as exc_info:
            await service.assign_tag(non_admin_user, global_tag.tag.id, "Issue", issue.id)
        assert "administrator" in str(exc_info.value).lower()

    async def test_non_admin_cannot_unassign_global(
        self, non_admin_user: User, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Only admins can unassign global tags."""
        service = TagService(async_db)
        global_tag = await service.create_tag(
            admin_user, "Global", color="red", scope="global"
        )
        _thread, issue, _plan = await _create_target_entities(async_db, non_admin_user)
        await service.assign_tag(admin_user, global_tag.tag.id, "Issue", issue.id)
        with pytest.raises(ForbiddenError) as exc_info:
            await service.unassign_tag(
                non_admin_user, global_tag.tag.id, "Issue", issue.id
            )
        assert "administrator" in str(exc_info.value).lower()


class TestPrivateTagCRUD:
    """Tests for private tag create/update/delete flows."""

    async def test_private_tag_update(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Owners can rename and recolor their private tags."""
        service = TagService(async_db)
        created = await service.create_tag(non_admin_user, "Old Name", color="red")
        tag = created.tag
        updated = await service.update_tag(
            non_admin_user, tag.id, name="New Name", color="green"
        )
        assert updated.name == "New Name"
        assert updated.normalized_name == "new name"
        assert updated.color == TAG_COLOR_PALETTE["green"]
        assert updated.updated_at >= tag.created_at

    async def test_private_tag_delete_cascades_assignments(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Deleting a private tag removes all of its assignments."""
        _thread, issue, _plan = await _create_target_entities(async_db, non_admin_user)
        service = TagService(async_db)
        created = await service.create_tag(non_admin_user, "ToDelete", color="red")
        tag = created.tag
        await service.assign_tag(non_admin_user, tag.id, "Issue", issue.id)
        await service.assign_tag(non_admin_user, tag.id, "Thread", _thread.id)
        result = await service.delete_tag(non_admin_user, tag.id)
        assert result.assignments_removed == 2
        count = await async_db.execute(
            select(func.count()).select_from(TagAssignment).where(
                TagAssignment.tag_id == tag.id
            )
        )
        assert count.scalar_one() == 0
        stored = await async_db.get(Tag, tag.id)
        assert stored is None

    async def test_admin_cannot_delete_another_users_private_tag(
        self, admin_user: User, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Admins cannot reach another user's private tag, even to delete it."""
        _thread, issue, _plan = await _create_target_entities(async_db, non_admin_user)
        service = TagService(async_db)
        created = await service.create_tag(non_admin_user, "Others Tag", color="red")
        tag = created.tag
        await service.assign_tag(non_admin_user, tag.id, "Issue", issue.id)
        with pytest.raises(NotFoundError):
            await service.delete_tag(admin_user, tag.id)
        assert await async_db.get(Tag, tag.id) is not None

    async def test_delete_nonexistent_tag_raises(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Deleting a missing tag reports it as not found."""
        service = TagService(async_db)
        with pytest.raises(NotFoundError) as exc_info:
            await service.delete_tag(non_admin_user, 99999)
        assert "does not exist" in str(exc_info.value).lower()

    async def test_unassign_removes_assignment(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Unassigning removes exactly the targeted assignment."""
        _thread, issue, _plan = await _create_target_entities(async_db, non_admin_user)
        service = TagService(async_db)
        created = await service.create_tag(non_admin_user, "Unassign Test", color="red")
        tag = created.tag
        assignment = await service.assign_tag(non_admin_user, tag.id, "Issue", issue.id)
        removed = await service.unassign_tag(non_admin_user, tag.id, "Issue", issue.id)
        assert removed.id == assignment.id
        count = await async_db.execute(
            select(func.count()).select_from(TagAssignment).where(
                TagAssignment.tag_id == tag.id
            )
        )
        assert count.scalar_one() == 0

    async def test_unassign_missing_assignment_raises(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Unassigning a tag that is not attached raises not-found."""
        created = await TagService(async_db).create_tag(
            non_admin_user, "Test", color="red"
        )
        tag = created.tag
        with pytest.raises(NotFoundError) as exc_info:
            await TagService(async_db).unassign_tag(non_admin_user, tag.id, "Issue", 1)
        assert "not assigned" in str(exc_info.value).lower()


class TestUsageReporting:
    """Tests for tag usage counting."""

    async def test_count_assignments(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Usage counts cover every target type."""
        thread, issue, plan = await _create_target_entities(async_db, admin_user)
        service = TagService(async_db)
        created = await service.create_tag(
            admin_user, "Count Test", color="red", scope="global"
        )
        tag = created.tag
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
            """Initialize the fake hook with per-tag reference sets."""
            self.items = items
            self.removed = 0

        async def cleanup_tag_references(
            self, db: AsyncSession, tag_id: int
        ) -> int:
            """Report the number of stored references for a deleted tag."""
            self.removed = len(self.items.get(tag_id, set()))
            return self.removed

    async def test_hook_is_run_on_tag_deletion(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Registered consumers run and their counts are reported."""
        service = TagService(async_db)
        created = await service.create_tag(admin_user, "Hooked", color="red")
        tag = created.tag
        hook = self.FakeRollFilterHook({tag.id: {1, 2, 3}})
        register_tag_deletion_hook(hook)
        try:
            result = await service.delete_tag(admin_user, tag.id)
            assert hook.removed == 3
            assert result.references_removed_by_consumers["FakeRollFilterHook"] == 3
        finally:
            unregister_tag_deletion_hook(hook)


class TestAPILayer:
    """Integration tests hitting the actual API routes."""

    async def test_list_tags_returns_global_and_private(
        self,
        admin_auth_client: AsyncClient,
        admin_user: User,
        async_db: AsyncSession,
    ) -> None:
        """GET /api/v1/tags/ lists global tags and the caller's private tags."""
        service = TagService(async_db)
        await service.create_tag(admin_user, "Global 1", color="red", scope="global")
        await service.create_tag(admin_user, "Admin Private", color="blue")

        resp = await admin_auth_client.get("/api/v1/tags/")
        assert resp.status_code == 200
        data = resp.json()
        tag_names = {t["name"] for t in data["tags"]}
        assert "Global 1" in tag_names
        assert "Admin Private" in tag_names

    async def test_create_private_tag_via_api(
        self,
        user_auth_client: AsyncClient,
        non_admin_user: User,
        async_db: AsyncSession,
    ) -> None:
        """POST /api/v1/tags/ creates a private tag for a non-admin user."""
        resp = await user_auth_client.post(
            "/api/v1/tags/", json={"name": "API Tag", "color": "red"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tag"]["name"] == "API Tag"
        assert data["tag"]["scope"] == "private"
        assert data["redirected_to_global"] is False

    async def test_create_global_tag_requires_admin(
        self, user_auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """POST /api/v1/tags/ with global scope is refused for non-admins."""
        resp = await user_auth_client.post(
            "/api/v1/tags/", json={"name": "Global", "color": "red", "scope": "global"}
        )
        assert resp.status_code == 403

    async def test_assign_via_api(
        self,
        user_auth_client: AsyncClient,
        non_admin_user: User,
        async_db: AsyncSession,
    ) -> None:
        """POST /api/v1/tags/{id}/assign/ attaches a private tag to an issue."""
        _thread, issue, _plan = await _create_target_entities(async_db, non_admin_user)
        tag_resp = await user_auth_client.post("/api/v1/tags/", json={"name": "API Tag"})
        tag_id = tag_resp.json()["tag"]["id"]
        resp = await user_auth_client.post(
            f"/api/v1/tags/{tag_id}/assign/",
            json={"target_type": "Issue", "target_id": issue.id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_type"] == "Issue"
        assert data["target_id"] == issue.id

    async def test_delete_cascades_and_reports_usage(
        self,
        user_auth_client: AsyncClient,
        non_admin_user: User,
        async_db: AsyncSession,
    ) -> None:
        """DELETE /api/v1/tags/{id}/ cascades assignments and reports usage."""
        thread, issue, _plan = await _create_target_entities(async_db, non_admin_user)
        tag_resp = await user_auth_client.post(
            "/api/v1/tags/", json={"name": "Cascade Test"}
        )
        tag_id = tag_resp.json()["tag"]["id"]
        await user_auth_client.post(
            f"/api/v1/tags/{tag_id}/assign/",
            json={"target_type": "Issue", "target_id": issue.id},
        )
        await user_auth_client.post(
            f"/api/v1/tags/{tag_id}/assign/",
            json={"target_type": "Thread", "target_id": thread.id},
        )
        resp = await user_auth_client.delete(f"/api/v1/tags/{tag_id}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["assignments_removed"] == 2
        assert data["references_removed_by_consumers"] == {}

    async def test_created_tag_survives_session_rollback(
        self,
        user_auth_client: AsyncClient,
        async_db: AsyncSession,
    ) -> None:
        """The route commits, so rolling the request session back keeps the tag."""
        resp = await user_auth_client.post(
            "/api/v1/tags/", json={"name": "Durable Tag"}
        )
        assert resp.status_code == 200
        tag_id = resp.json()["tag"]["id"]

        await async_db.rollback()

        stored = await async_db.execute(select(Tag).where(Tag.id == tag_id))
        persisted = stored.scalar_one_or_none()
        assert persisted is not None
        assert persisted.name == "Durable Tag"

    async def test_assigned_tag_survives_session_rollback(
        self,
        user_auth_client: AsyncClient,
        non_admin_user: User,
        async_db: AsyncSession,
    ) -> None:
        """Assignment writes commit too, not only tag rows."""
        _thread, issue, _plan = await _create_target_entities(async_db, non_admin_user)
        tag_resp = await user_auth_client.post(
            "/api/v1/tags/", json={"name": "Durable Assignment"}
        )
        tag_id = tag_resp.json()["tag"]["id"]
        assign_resp = await user_auth_client.post(
            f"/api/v1/tags/{tag_id}/assign/",
            json={"target_type": "Issue", "target_id": issue.id},
        )
        assert assign_resp.status_code == 200
        assignment_id = assign_resp.json()["id"]

        await async_db.rollback()

        stored = await async_db.execute(
            select(TagAssignment).where(TagAssignment.id == assignment_id)
        )
        assert stored.scalar_one_or_none() is not None


class TestTagScopeEnum:
    """Tests validating the schema enum handling."""

    async def test_schema_scope_coercion(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """The scope schema exposes the global and private values."""
        from app.schemas.tags import TagScope

        assert TagScope.PRIVATE == "private"
        assert TagScope.GLOBAL == "global"

    async def test_schema_target_type_coercion(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """The target-type schema exposes the three v1 target types."""
        from app.schemas.tags import TagTargetType

        assert TagTargetType.ISSUE == "Issue"
        assert TagTargetType.THREAD == "Thread"
        assert TagTargetType.CONTINUITY_PLAN == "ContinuityPlan"

    def test_target_type_enum_matches_registry(self) -> None:
        """The schema enum and the service's supported-type tuple agree.

        ``TAG_TARGET_TYPES`` drives the "Unsupported target type" error text and
        the request schema drives validation; a drift between them would make
        the API accept or reject different vocabularies.
        """
        from app.schemas.tags import TagTargetType

        assert tuple(member.value for member in TagTargetType) == TAG_TARGET_TYPES

    def test_scope_enum_drives_request_validation(self) -> None:
        """The request model validates scope against the enum, not free text."""
        from app.schemas.tags import TagCreate, TagScope

        request = TagCreate(name="X", scope="global")
        assert request.scope == TagScope.GLOBAL

        with pytest.raises(ValueError):
            TagCreate(name="X", scope="everyone")

    def test_scope_enum_covers_private_default(self) -> None:
        """An omitted scope defaults to private."""
        from app.schemas.tags import TagCreate, TagScope

        assert TagCreate(name="X").scope == TagScope.PRIVATE


class TestScopeCoercion:
    """Tests for enum-valued scope requests reaching the service."""

    async def test_enum_scope_private_creates_private_tag(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Passing the ``TagScope`` enum member behaves like the wire string."""
        from app.schemas.tags import TagScope

        result = await TagService(async_db).create_tag(
            non_admin_user, "Enum Scope", color="red", scope=TagScope.PRIVATE
        )
        assert result.tag.scope == "private"
        assert result.tag.owner_user_id == non_admin_user.id

    async def test_enum_scope_global_requires_admin(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """The enum-valued global scope still requires an administrator."""
        from app.schemas.tags import TagScope

        with pytest.raises(ForbiddenError):
            await TagService(async_db).create_tag(
                non_admin_user, "Enum Global", color="red", scope=TagScope.GLOBAL
            )

    async def test_enum_scope_global_allowed_for_admin(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """An admin may create a global tag with the enum scope."""
        from app.schemas.tags import TagScope

        result = await TagService(async_db).create_tag(
            admin_user, "Enum Global", color="red", scope=TagScope.GLOBAL
        )
        assert result.tag.scope == "global"
        assert result.tag.owner_user_id is None

    async def test_unknown_scope_rejected(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """An unrecognized scope string is refused rather than defaulted."""
        with pytest.raises(InvalidRequestError):
            await TagService(async_db).create_tag(
                admin_user, "Bad Scope", color="red", scope="everyone"
            )


class TestColorNormalization:
    """Tests for canonical palette hex normalization."""

    def test_lowercase_hex_normalizes_to_palette_value(self) -> None:
        """A lowercase hex request stores the canonical palette casing."""
        name, hex_value = validate_tag_color("#3b82f6")
        assert (name, hex_value) == ("blue", TAG_COLOR_PALETTE["blue"])

    async def test_lowercase_hex_stored_canonically(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Tag rows store the palette's canonical hex, not the request casing."""
        result = await TagService(async_db).create_tag(
            non_admin_user, "Lower Hex", color="#dc2626"
        )
        assert result.tag.color == DEFAULT_TAG_COLOR_HEX

    async def test_padded_name_is_trimmed(
        self, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Surrounding whitespace on a palette name is tolerated."""
        result = await TagService(async_db).create_tag(
            non_admin_user, "Padded Color", color="  red  "
        )
        assert result.tag.color == DEFAULT_TAG_COLOR_HEX


class TestTargetDeletionCleanup:
    """Tests for explicit cleanup of assignments on target deletion.

    Polymorphic ``target_id`` values have no foreign key, so every target
    deletion path must remove the assignments that pointed at the deleted rows.
    """

    async def test_purge_removes_assignments_for_target(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Assignments for one target type and id are removed together."""
        thread, issue, plan = await _create_target_entities(async_db, admin_user)
        service = TagService(async_db)
        created = await service.create_tag(admin_user, "Cleanup", color="red")
        tag_id = created.tag.id
        await service.assign_tag(admin_user, tag_id, "Issue", issue.id)
        await service.assign_tag(admin_user, tag_id, "Thread", thread.id)
        await service.assign_tag(admin_user, tag_id, "ContinuityPlan", plan.id)

        removed = await purge_target_assignments(async_db, "Issue", [issue.id])
        assert removed == 1

        remaining = await async_db.execute(
            select(TagAssignment).where(TagAssignment.tag_id == tag_id)
        )
        assert {row.target_type for row in remaining.scalars().all()} == {
            "Thread",
            "ContinuityPlan",
        }

    async def test_purge_with_no_ids_is_a_noop(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """An empty target list never reaches the database."""
        assert await purge_target_assignments(async_db, "Thread", []) == 0

    async def test_issue_deletion_removes_its_assignments(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """``delete_issue`` leaves no assignment pointing at the deleted issue."""
        from app.services.issue import delete_issue

        _thread, issue, _plan = await _create_target_entities(async_db, admin_user)
        service = TagService(async_db)
        created = await service.create_tag(admin_user, "Issue Cleanup", color="red")
        tag_id = created.tag.id
        await service.assign_tag(admin_user, tag_id, "Issue", issue.id)

        await delete_issue(async_db, issue.id, admin_user.id)

        remaining = await async_db.execute(
            select(TagAssignment).where(TagAssignment.tag_id == tag_id)
        )
        assert remaining.scalars().all() == []

    async def test_thread_deletion_removes_thread_and_issue_assignments(
        self, admin_user: User, async_db: AsyncSession
    ) -> None:
        """``delete_thread`` clears the thread's and its issues' assignments."""
        from app.services.thread_service import delete_thread

        thread, issue, _plan = await _create_target_entities(async_db, admin_user)
        service = TagService(async_db)
        created = await service.create_tag(admin_user, "Thread Cleanup", color="red")
        tag_id = created.tag.id
        await service.assign_tag(admin_user, tag_id, "Thread", thread.id)
        await service.assign_tag(admin_user, tag_id, "Issue", issue.id)

        await delete_thread(async_db, admin_user.id, thread.id)

        remaining = await async_db.execute(
            select(TagAssignment).where(TagAssignment.tag_id == tag_id)
        )
        assert remaining.scalars().all() == []

    async def test_continuity_plan_deletion_removes_its_assignments(
        self, admin_auth_client: AsyncClient, admin_user: User, async_db: AsyncSession
    ) -> None:
        """Deleting a reading plan clears the assignments that pointed at it."""
        _thread, _issue, plan = await _create_target_entities(async_db, admin_user)
        created = await TagService(async_db).create_tag(
            admin_user, "Plan Cleanup", color="red", scope="global"
        )
        tag_id = created.tag.id
        await TagService(async_db).assign_tag(
            admin_user, tag_id, "ContinuityPlan", plan.id
        )

        resp = await admin_auth_client.delete(f"/api/v1/continuity-plans/{plan.id}")
        assert resp.status_code == 204

        remaining = await async_db.execute(
            select(TagAssignment).where(TagAssignment.tag_id == tag_id)
        )
        assert remaining.scalars().all() == []


class TestSchemaRoundTrip:
    """Tests for the tag API request/response contracts."""

    async def test_invalid_scope_returns_422(
        self, admin_auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """An unsupported scope value is rejected by request validation."""
        resp = await admin_auth_client.post(
            "/api/v1/tags/", json={"name": "Bad Scope", "scope": "everyone"}
        )
        assert resp.status_code == 422

    async def test_invalid_target_type_returns_422(
        self, user_auth_client: AsyncClient, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """An unsupported target type is rejected by request validation."""
        _thread, issue, _plan = await _create_target_entities(async_db, non_admin_user)
        tag_resp = await user_auth_client.post("/api/v1/tags/", json={"name": "Target Enum"})
        tag_id = tag_resp.json()["tag"]["id"]
        resp = await user_auth_client.post(
            f"/api/v1/tags/{tag_id}/assign/",
            json={"target_type": "Publisher", "target_id": issue.id},
        )
        assert resp.status_code == 422

    async def test_private_tag_detail_is_404_for_other_users(
        self, user_auth_client: AsyncClient, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """The detail route never confirms another user's private tag exists."""
        await TagService(async_db).create_tag(non_admin_user, "Hidden")
        resp = await user_auth_client.get("/api/v1/tags/1/")
        assert resp.status_code == 404

    async def test_usage_route_is_hidden_for_other_users(
        self, user_auth_client: AsyncClient, non_admin_user: User, async_db: AsyncSession
    ) -> None:
        """Usage counts cannot be probed for another user's private tag."""
        await TagService(async_db).create_tag(non_admin_user, "Hidden Usage")
        resp = await user_auth_client.get("/api/v1/tags/1/usage/")
        assert resp.status_code == 404
