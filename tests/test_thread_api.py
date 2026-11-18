"""Tests for Thread API endpoints."""

import pytest
from datetime import UTC, datetime, timedelta
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Issue, ReadingSession, Thread
from app.services.thread_service import list_queue_threads
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_reactivate_thread_uses_max_numeric_issue_number(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Reactivation appends regular issue numbers after the highest numeric issue."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Completed Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=4,
        status="completed",
        user_id=user.id,
        total_issues=11,
        reading_progress="completed",
        next_unread_issue_id=None,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    for position, issue_number in enumerate(
        [*(str(i) for i in range(1, 11)), "Annual 1"],
        start=1,
    ):
        async_db.add(
            Issue(
                thread_id=thread.id,
                issue_number=issue_number,
                position=position,
                status="read",
                read_at=datetime.now(UTC),
            )
        )
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/threads/reactivate",
        json={"thread_id": thread.id, "issues_to_add": 2},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_issues"] == 13
    assert data["issues_remaining"] == 2
    assert data["next_unread_issue_number"] == "11"

    result = await async_db.execute(
        select(Issue)
        .where(Issue.thread_id == thread.id)
        .order_by(Issue.position, Issue.id)
    )
    issues = result.scalars().all()

    assert [issue.issue_number for issue in issues[-2:]] == ["11", "12"]
    assert [issue.position for issue in issues[-2:]] == [12, 13]


















@pytest.mark.asyncio
async def test_create_thread_without_total_issues_maintains_backward_compat(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Creating thread without total_issues uses old system (backward compat)."""
    response = await auth_client.post(
        "/api/v1/threads/",
        json={
            "title": "Old Style Thread",
            "format": "Comic",
            "issues_remaining": 10,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Old Style Thread"
    assert data["issues_remaining"] == 10
    assert data["total_issues"] is None
    assert data["reading_progress"] is None

    thread = await async_db.get(Thread, data["id"])
    assert thread is not None
    assert thread.issues_remaining == 10
    assert thread.total_issues is None
    assert not thread.uses_issue_tracking()


@pytest.mark.asyncio
async def test_create_thread_with_total_issues_enables_tracking(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Creating thread with total_issues enables issue tracking."""
    response = await auth_client.post(
        "/api/v1/threads/",
        json={
            "title": "New Style Thread",
            "format": "Comic",
            "issues_remaining": 10,
            "total_issues": 25,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "New Style Thread"
    assert data["total_issues"] == 25
    assert data["reading_progress"] is None

    thread = await async_db.get(Thread, data["id"])
    assert thread is not None
    assert thread.total_issues == 25
    assert thread.uses_issue_tracking()

    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 0


@pytest.mark.asyncio
async def test_thread_create_schema_accepts_total_issues() -> None:
    """ThreadCreate schema accepts optional total_issues field."""
    from app.schemas import ThreadCreate

    schema = ThreadCreate(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        total_issues=25,
    )
    assert schema.total_issues == 25

    schema_without = ThreadCreate(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
    )
    assert schema_without.total_issues is None


@pytest.mark.asyncio
async def test_thread_create_schema_rejects_whitespace_title() -> None:
    """ThreadCreate schema rejects whitespace-only titles."""
    from app.schemas import ThreadCreate
    from pydantic import ValidationError

    # Whitespace-only title
    with pytest.raises(ValidationError) as exc_info:
        ThreadCreate(
            title="  ",
            format="Comic",
            issues_remaining=10,
        )
    assert "whitespace" in str(exc_info.value).lower()

    # Tab-only title
    with pytest.raises(ValidationError) as exc_info:
        ThreadCreate(
            title="\t\t",
            format="Comic",
            issues_remaining=10,
        )
    assert "whitespace" in str(exc_info.value).lower()

    # Newline-only title
    with pytest.raises(ValidationError) as exc_info:
        ThreadCreate(
            title="\n\n",
            format="Comic",
            issues_remaining=10,
        )
    assert "whitespace" in str(exc_info.value).lower()

    # Empty title (already covered by min_length=1, but verify)
    with pytest.raises(ValidationError):
        ThreadCreate(
            title="",
            format="Comic",
            issues_remaining=10,
        )


@pytest.mark.asyncio
async def test_thread_update_schema_rejects_whitespace_title() -> None:
    """ThreadUpdate schema rejects whitespace-only titles."""
    from app.schemas import ThreadUpdate
    from pydantic import ValidationError

    # Whitespace-only title
    with pytest.raises(ValidationError) as exc_info:
        ThreadUpdate(title="  ")
    assert "whitespace" in str(exc_info.value).lower()

    # Tab-only title
    with pytest.raises(ValidationError) as exc_info:
        ThreadUpdate(title="\t\t")
    assert "whitespace" in str(exc_info.value).lower()

    # Newline-only title
    with pytest.raises(ValidationError) as exc_info:
        ThreadUpdate(title="\n\n")
    assert "whitespace" in str(exc_info.value).lower()

    # Empty title should be rejected
    with pytest.raises(ValidationError):
        ThreadUpdate(title="")

    # None title should be allowed (not updating)
    schema = ThreadUpdate(title=None)
    assert schema.title is None




@pytest.mark.asyncio
async def test_stale_endpoint_excludes_blocked_threads(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Blocked stale threads should not appear in the stale endpoint."""
    user = await get_or_create_user_async(async_db)
    now = datetime.now(UTC)
    stale_date = now - timedelta(days=60)

    blocked_thread = Thread(
        title="Blocked Stale Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        last_activity_at=stale_date,
        is_blocked=True,
        created_at=now,
    )
    async_db.add(blocked_thread)
    await async_db.commit()

    response = await auth_client.get("/api/v1/threads/stale?days=30")
    assert response.status_code == 200
    data = response.json()
    thread_ids = {t["id"] for t in data}
    assert blocked_thread.id not in thread_ids


@pytest.mark.asyncio
async def test_stale_endpoint_includes_unblocked_stale_threads(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Unblocked stale threads should appear in the stale endpoint."""
    user = await get_or_create_user_async(async_db)
    now = datetime.now(UTC)
    stale_date = now - timedelta(days=60)

    unblocked_thread = Thread(
        title="Unblocked Stale Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        last_activity_at=stale_date,
        is_blocked=False,
        created_at=now,
    )
    async_db.add(unblocked_thread)
    await async_db.commit()

    response = await auth_client.get("/api/v1/threads/stale?days=30")
    assert response.status_code == 200
    data = response.json()
    thread_ids = {t["id"] for t in data}
    assert unblocked_thread.id in thread_ids


@pytest.mark.asyncio
async def test_stale_endpoint_excludes_snoozed_threads(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Stale endpoint excludes threads that are currently snoozed in the session."""
    user = await get_or_create_user_async(async_db)
    now = datetime.now(UTC)
    stale_date = now - timedelta(days=60)

    stale_thread = Thread(
        title="Stale Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        last_activity_at=stale_date,
        created_at=now,
    )
    snoozed_stale_thread = Thread(
        title="Snoozed Stale Thread",
        format="Comic",
        issues_remaining=3,
        queue_position=2,
        status="active",
        user_id=user.id,
        last_activity_at=stale_date,
        created_at=now,
    )
    async_db.add_all([stale_thread, snoozed_stale_thread])
    await async_db.flush()

    session = ReadingSession(
        user_id=user.id,
        started_at=now,
        snoozed_thread_ids=[snoozed_stale_thread.id],
    )
    async_db.add(session)
    await async_db.commit()

    response = await auth_client.get("/api/v1/threads/stale?days=30")
    assert response.status_code == 200
    data = response.json()
    thread_ids = {t["id"] for t in data}
    assert stale_thread.id in thread_ids
    assert snoozed_stale_thread.id not in thread_ids


@pytest.mark.asyncio
async def test_stale_endpoint_bounded_by_page_size(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Stale endpoint respects page_size bound at the database."""
    user = await get_or_create_user_async(async_db)
    now = datetime.now(UTC)
    stale_date = now - timedelta(days=60)
    for i in range(3):
        async_db.add(
            Thread(
                title=f"Stale {i}",
                format="Comic",
                issues_remaining=1,
                queue_position=1,
                status="active",
                user_id=user.id,
                last_activity_at=stale_date,
                is_blocked=False,
                created_at=now,
            )
        )
    await async_db.commit()
    response = await auth_client.get("/api/v1/threads/stale?days=30&page_size=2")
    assert response.status_code == 200
    assert len(response.json()) <= 2


@pytest.mark.asyncio
async def test_list_threads_issues_remaining_correct(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """issues_remaining reflects live unread count for migrated threads."""
    user = await get_or_create_user_async(async_db)

    threads_data: list[tuple[str, int, int, int]] = [
        ("Series A", 10, 3, 1),
        ("Series B", 5, 1, 2),
        ("Series C", 20, 0, 3),
    ]
    expected_remaining: dict[int, int] = {}

    for title, total, unread, pos in threads_data:
        thread = Thread(
            title=title,
            format="Comic",
            issues_remaining=0,
            queue_position=pos,
            status="active",
            user_id=user.id,
            total_issues=total,
            reading_progress="in_progress",
            created_at=datetime.now(UTC),
        )
        async_db.add(thread)
        await async_db.flush()
        expected_remaining[thread.id] = unread

        for issue_num in range(1, total + 1):
            status = "unread" if issue_num > (total - unread) else "read"
            async_db.add(
                Issue(
                    thread_id=thread.id,
                    issue_number=str(issue_num),
                    position=issue_num,
                    status=status,
                    read_at=datetime.now(UTC) if status == "read" else None,
                )
            )
    await async_db.commit()

    page = await list_queue_threads(
        async_db, user.id, search=None, sort="position", page_size=10, page_token=None
    )

    thread_map = {t.id: t for t in page.threads}
    for tid, expected in expected_remaining.items():
        assert thread_map[tid].issues_remaining == expected, (
            f"Thread {tid} expected {expected} unread, got {thread_map[tid].issues_remaining}"
        )


@pytest.mark.asyncio
async def test_list_threads_mixed_migrated_unmigrated(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Unmigrated threads report legacy column; migrated threads report true count."""
    user = await get_or_create_user_async(async_db)

    unmigrated = Thread(
        title="Old Thread",
        format="Comic",
        issues_remaining=42,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(unmigrated)
    await async_db.flush()

    migrated = Thread(
        title="New Thread",
        format="Comic",
        issues_remaining=99,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=10,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(migrated)
    await async_db.flush()

    for i in range(1, 11):
        async_db.add(
            Issue(
                thread_id=migrated.id,
                issue_number=str(i),
                position=i,
                status="unread" if i <= 3 else "read",
                read_at=datetime.now(UTC) if i > 3 else None,
            )
        )
    await async_db.commit()

    page = await list_queue_threads(
        async_db, user.id, search=None, sort="position", page_size=10, page_token=None
    )

    thread_map = {t.id: t for t in page.threads}

    assert thread_map[unmigrated.id].issues_remaining == 42
    assert thread_map[migrated.id].issues_remaining == 3


@pytest.mark.asyncio
async def test_bulk_issues_remaining_no_n_plus_one(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """List endpoint uses a single batched issue-stats query instead of N per-thread COUNTs."""
    from sqlalchemy import event

    user = await get_or_create_user_async(async_db)

    thread_count = 20
    for i in range(thread_count):
        t = Thread(
            title=f"Bulk Thread {i}",
            format="Comic",
            issues_remaining=0,
            queue_position=i + 1,
            status="active",
            user_id=user.id,
            total_issues=5,
            reading_progress="in_progress",
            created_at=datetime.now(UTC),
        )
        async_db.add(t)
        await async_db.flush()

        for j in range(1, 6):
            async_db.add(
                Issue(
                    thread_id=t.id,
                    issue_number=str(j),
                    position=j,
                    status="unread" if j <= 2 else "read",
                    read_at=datetime.now(UTC) if j > 2 else None,
                )
            )
    await async_db.commit()


    captured: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        captured.append(str(statement))

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        page = await list_queue_threads(
            async_db, user.id, search=None, sort="position", page_size=50, page_token=None
        )
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)

    assert len(page.threads) == thread_count

    for t_resp in page.threads:
        assert t_resp.issues_remaining == 2, (
            f"Thread {t_resp.id} expected 2 unread, got {t_resp.issues_remaining}"
        )

    per_thread_counts = [
        s
        for s in captured
        if "count(" in s.lower()
        and "from issues" in s.lower()
        and "group by" not in s.lower()
    ]
    assert len(per_thread_counts) == 0, (
        f"Found {len(per_thread_counts)} per-thread COUNT queries: {per_thread_counts}"
    )
    bulk_counts = [
        s
        for s in captured
        if "from issues" in s.lower()
        and "issue_external_identity_mappings" not in s.lower()
        and "external_identities" not in s.lower()
    ]
    assert len(bulk_counts) == 1, (
        f"Expected 1 batched issue-stats query, found {len(bulk_counts)}: {bulk_counts}"
    )

    assert len(captured) < 15, (
        f"Expected bounded query count (<15), got {len(captured)}: {captured}"
    )




















@pytest.mark.asyncio
async def test_create_thread_normalizes_format_variants(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Thread creation normalizes Comic/Comics/digital to canonical forms."""
    cases = [
        ("Comic", "Comic"),
        ("Comics", "Comic"),
        ("comic", "Comic"),
        ("comics", "Comic"),
        ("digital", "Digital"),
        ("Digital", "Digital"),
        ("Trade Paperback", "Trade Paperback"),
    ]

    for raw, expected in cases:
        response = await auth_client.post(
            "/api/v1/threads/",
            json={"title": f"Thread {raw}", "format": raw, "issues_remaining": 1},
        )
        assert response.status_code == 201, f"Failed for {raw}: {response.text}"
        data = response.json()
        assert data["format"] == expected, f"Expected {expected} for {raw}, got {data['format']}"

        result = await async_db.execute(
            select(Thread).where(Thread.id == data["id"])
        )
        db_thread = result.scalar_one()
        assert db_thread.format == expected, f"DB format mismatch for {raw}"


@pytest.mark.asyncio
async def test_update_thread_normalizes_format_variants(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Thread update normalizes Comic/Comics/digital to canonical forms."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Format Test",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    cases = [
        ("Comics", "Comic"),
        ("comics", "Comic"),
        ("digital", "Digital"),
        ("Manga", "Manga"),
    ]

    for raw, expected in cases:
        response = await auth_client.put(
            f"/api/v1/threads/{thread.id}",
            json={"format": raw},
        )
        assert response.status_code == 200, f"Failed for {raw}: {response.text}"
        data = response.json()
        assert data["format"] == expected, f"Expected {expected} for {raw}, got {data['format']}"

        await async_db.refresh(thread)
        assert thread.format == expected, f"DB format mismatch for {raw}"


@pytest.mark.asyncio
async def test_update_thread_clears_notes_when_field_is_sent(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A cleared Notes field persists as no notes (issue #3629).

    Notes use explicit-presence semantics: sending an emptied string or an
    explicit ``null`` clears the stored note, while leaving the field out of the
    request keeps the existing note untouched.
    """
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Notes Test",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        notes="Read the tie-in first",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    # An emptied Notes field must clear the stored note instead of being treated
    # as "leave unchanged".
    response = await auth_client.put(
        f"/api/v1/threads/{thread.id}",
        json={"title": "Notes Test", "format": "Comic", "notes": ""},
    )
    assert response.status_code == 200, response.text
    assert response.json()["notes"] is None

    await async_db.refresh(thread)
    assert thread.notes is None

    # A whitespace-only value is also "no notes".
    thread.notes = "Keep the annual out of the run"
    await async_db.commit()
    response = await auth_client.put(
        f"/api/v1/threads/{thread.id}",
        json={"notes": "   "},
    )
    assert response.status_code == 200, response.text
    assert response.json()["notes"] is None

    await async_db.refresh(thread)
    assert thread.notes is None

    # An explicit null clears too.
    thread.notes = "Has notes again"
    await async_db.commit()
    response = await auth_client.put(
        f"/api/v1/threads/{thread.id}",
        json={"notes": None},
    )
    assert response.status_code == 200, response.text
    assert response.json()["notes"] is None

    await async_db.refresh(thread)
    assert thread.notes is None

    # Omitting the field leaves the existing note in place.
    thread.notes = "Preserve me"
    await async_db.commit()
    response = await auth_client.put(
        f"/api/v1/threads/{thread.id}",
        json={"title": "Renamed Notes Test"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["notes"] == "Preserve me"

    await async_db.refresh(thread)
    assert thread.notes == "Preserve me"


@pytest.mark.asyncio
async def test_queue_items_show_normalized_format(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Queue list items render normalized format values."""
    user = await get_or_create_user_async(async_db)

    for fmt in ("Comics", "digital", "Manga"):
        thread = Thread(
            title=f"Test {fmt}",
            format=fmt,
            issues_remaining=1,
            queue_position=1,
            status="active",
            user_id=user.id,
            created_at=datetime.now(UTC),
        )
        async_db.add(thread)
    await async_db.commit()

    page = await list_queue_threads(
        async_db, user.id, search=None, sort="position", page_size=50, page_token=None
    )

    formats = {item.format for item in page.threads}
    assert "Comic" in formats
    assert "Digital" in formats
    assert "Manga" in formats
    assert "Comics" not in formats
    assert "digital" not in formats


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Comic", "Comic"),
        ("Comics", "Comic"),
        ("comic", "Comic"),
        ("COMICS", "Comic"),
        (" digital ", "Digital"),
        ("Digital", "Digital"),
        ("Trade Paperback", "Trade Paperback"),
        ("Manga", "Manga"),
        ("Other", "Other"),
    ],
)
def test_normalize_format_value_maps_variants(raw: str, expected: str) -> None:
    """Every incoherent production variant maps into the canonical vocabulary."""
    from app.models.thread import normalize_format_value

    assert normalize_format_value(raw) == expected


def test_normalize_format_value_preserves_unknown_formats() -> None:
    """Unknown formats are normalized without loss, not dropped or coerced."""
    from app.models.thread import normalize_format_value

    assert normalize_format_value("Webtoon") == "Webtoon"
    assert normalize_format_value("  Graphic Novel  ") == "Graphic Novel"


def test_normalize_format_value_covers_issue_variants_with_no_data_loss() -> None:
    """Issue #1647 variants collapse into a single canonical set (no loss)."""
    from app.models.thread import normalize_format_value

    source_values = ["Comic", "Comics", "comic", "digital", "Digital"]
    normalized = {normalize_format_value(value) for value in source_values}
    assert normalized == {"Comic", "Digital"}


def test_normalize_notes_value_stores_empty_notes_as_none() -> None:
    """An empty or whitespace-only note is stored as "no notes" (#3629)."""
    from app.models.thread import normalize_notes_value

    assert normalize_notes_value(None) is None
    assert normalize_notes_value("") is None
    assert normalize_notes_value("   ") is None
    assert normalize_notes_value("\n\t ") is None


def test_normalize_notes_value_preserves_non_empty_notes_verbatim() -> None:
    """Real notes, including internal and edge whitespace, survive unchanged."""
    from app.models.thread import normalize_notes_value

    assert normalize_notes_value("Read the tie-in first") == "Read the tie-in first"
    assert normalize_notes_value("Line one\n\nLine two") == "Line one\n\nLine two"
    # A non-empty note keeps its surrounding whitespace; only *all-whitespace*
    # values collapse to "no notes".
    assert normalize_notes_value("  padded  ") == "  padded  "

