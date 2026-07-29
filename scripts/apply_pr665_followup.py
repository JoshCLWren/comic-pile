"""Apply the valid second-pass review fixes to PR #665."""

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one match in {path}, found {count}: {old[:80]!r}")
    file_path.write_text(text.replace(old, new, 1))


replace_once(
    "comic_pile/dependencies.py",
    "from app.cache import TTL, cached, invalidate_cache\n",
    "from app.cache import TTL, cached\n",
)
replace_once(
    "comic_pile/dependencies.py",
    '''@cached(ttl=TTL.SHORT)
async def get_blocked_thread_ids(user_id: int, db: AsyncSession) -> set[int]:
    """Return thread IDs blocked by unsatisfied issue-level dependencies for a user."""
    source_issue = Issue.__table__.alias("source_issue")
    next_unread_issue = Issue.__table__.alias("next_unread_issue")
    target_thread = Thread.__table__.alias("target_thread")
    source = Thread.__table__.alias("source_thread")

    issue_result = await db.execute(
        select(target_thread.c.id)
        .join(
            next_unread_issue,
            next_unread_issue.c.id == target_thread.c.next_unread_issue_id,
        )
        .join(Dependency, Dependency.target_issue_id == next_unread_issue.c.id)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(source, source_issue.c.thread_id == source.c.id)
        .where(target_thread.c.user_id == user_id)
        .where(source.c.user_id == user_id)
        .where(source_issue.c.status != "read")
        .where(target_thread.c.next_unread_issue_id.isnot(None))
        .distinct()
    )
    return {row[0] for row in issue_result.all()}
''',
    '''async def _get_blocked_thread_ids_uncached(user_id: int, db: AsyncSession) -> set[int]:
    """Read blocked thread IDs directly from the current database transaction."""
    source_issue = Issue.__table__.alias("source_issue")
    next_unread_issue = Issue.__table__.alias("next_unread_issue")
    target_thread = Thread.__table__.alias("target_thread")
    source = Thread.__table__.alias("source_thread")

    issue_result = await db.execute(
        select(target_thread.c.id)
        .join(
            next_unread_issue,
            next_unread_issue.c.id == target_thread.c.next_unread_issue_id,
        )
        .join(Dependency, Dependency.target_issue_id == next_unread_issue.c.id)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(source, source_issue.c.thread_id == source.c.id)
        .where(target_thread.c.user_id == user_id)
        .where(source.c.user_id == user_id)
        .where(source_issue.c.status != "read")
        .where(target_thread.c.next_unread_issue_id.isnot(None))
        .distinct()
    )
    return {row[0] for row in issue_result.all()}


@cached(ttl=TTL.SHORT)
async def get_blocked_thread_ids(user_id: int, db: AsyncSession) -> set[int]:
    """Return cached blocked thread IDs for non-transactional reads."""
    return await _get_blocked_thread_ids_uncached(user_id, db)
''',
)
replace_once(
    "comic_pile/dependencies.py",
    '''async def update_thread_blocked_status(thread_id: int, user_id: int, db: AsyncSession) -> None:
    """Recalculate one thread's denormalized blocked flag."""
    blocked_ids = await get_blocked_thread_ids(user_id, db)
''',
    '''async def update_thread_blocked_status(thread_id: int, user_id: int, db: AsyncSession) -> None:
    """Recalculate one thread's denormalized blocked flag."""
    blocked_ids = await _get_blocked_thread_ids_uncached(user_id, db)
''',
)
replace_once(
    "comic_pile/dependencies.py",
    '''async def refresh_user_blocked_status(user_id: int, db: AsyncSession) -> None:
    """Recalculate blocked flags for all threads of a user."""
    await invalidate_cache(f"cache:get_blocked_thread_ids:{user_id}:")
    blocked_ids = await get_blocked_thread_ids(user_id, db)
''',
    '''async def refresh_user_blocked_status(user_id: int, db: AsyncSession) -> None:
    """Recalculate blocked flags without caching uncommitted transaction state."""
    blocked_ids = await _get_blocked_thread_ids_uncached(user_id, db)
''',
)

replace_once(
    "tests/test_cache.py",
    '''async def test_cache_session_details_warm_then_rate(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
''',
    '''async def test_cache_session_details_warm_then_rate(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict,
) -> None:
''',
)
replace_once(
    "tests/test_cache.py",
    '''        status="active",
        user_id=1,
    )
    async_db.add(thread)
    await async_db.commit()

    # Roll dice first so rate endpoint has an active thread
''',
    '''        status="active",
        user_id=sample_data["user"].id,
    )
    async_db.add(thread)
    await async_db.commit()

    # Roll dice first so rate endpoint has an active thread
''',
)
replace_once(
    "tests/test_cache.py",
    '''async def test_cache_session_snapshots_warm_then_rate(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
''',
    '''async def test_cache_session_snapshots_warm_then_rate(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict,
) -> None:
''',
)
replace_once(
    "tests/test_cache.py",
    '''        title="Snap Session Test",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=1,
    )
''',
    '''        title="Snap Session Test",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=sample_data["user"].id,
    )
''',
)

cache_tests = Path("tests/test_cache.py")
cache_tests.write_text(
    cache_tests.read_text()
    + '''

@pytest.mark.asyncio
async def test_refresh_blocked_status_does_not_populate_cache_before_commit(
    async_db: AsyncSession,
    sample_data: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transactional blocked-status refresh bypasses the cache-backed read."""
    import comic_pile.dependencies as dependencies_module

    user = sample_data["user"]
    cache_key = f"cache:get_blocked_thread_ids:{user.id}:"
    await cache.delete(cache_key)

    async def fail_if_cached_read_is_used(user_id: int, db: AsyncSession) -> set[int]:
        raise AssertionError(f"cached blocked-thread read used for user {user_id}")

    monkeypatch.setattr(
        dependencies_module,
        "get_blocked_thread_ids",
        fail_if_cached_read_is_used,
    )

    await dependencies_module.refresh_user_blocked_status(user.id, async_db)

    assert await cache.get(cache_key) is None
    await async_db.rollback()
'''
)
