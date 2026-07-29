"""Repair the PR 665 cache regression test setup."""

from pathlib import Path


path = Path("tests/test_cache.py")
text = path.read_text()


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one match, found {count}: {old[:100]!r}")
    text = text.replace(old, new, 1)


replace_once(
    'pytest.skip("REDIS_URL is required for cache regression tests")',
    'pytest.skip(reason="REDIS_URL is required for cache regression tests")',
)

replace_once(
    "from app.models import Dependency, Issue, Thread\n",
    "from app.models import Dependency, Issue, Thread, User\n",
)

replace_once(
    "from comic_pile.dependencies import get_blocked_thread_ids\n\n\n",
    '''from comic_pile.dependencies import get_blocked_thread_ids


async def _authenticated_user_id(async_db: AsyncSession, test_username: str) -> int:
    """Return the user ID created by the authenticated client fixture."""
    result = await async_db.execute(select(User.id).where(User.username == test_username))
    return result.scalar_one()


''',
)

replace_once(
    '''async def test_cache_session_details_warm_then_rate(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict,
) -> None:
''',
    '''async def test_cache_session_details_warm_then_rate(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    test_username: str,
) -> None:
''',
)

replace_once(
    '''    from app.models import Thread as ThreadModel

    thread = ThreadModel(
        title="Rate Session Test",
''',
    '''    from app.models import Thread as ThreadModel

    user_id = await _authenticated_user_id(async_db, test_username)
    thread = ThreadModel(
        title="Rate Session Test",
''',
)

replace_once(
    '''        title="Rate Session Test",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=sample_data["user"].id,
''',
    '''        title="Rate Session Test",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user_id,
''',
)

replace_once(
    '''async def test_cache_session_snapshots_warm_then_rate(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict,
) -> None:
''',
    '''async def test_cache_session_snapshots_warm_then_rate(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    test_username: str,
) -> None:
''',
)

replace_once(
    '''    from app.models import Thread as ThreadModel

    thread = ThreadModel(
        title="Snap Session Test",
''',
    '''    from app.models import Thread as ThreadModel

    user_id = await _authenticated_user_id(async_db, test_username)
    thread = ThreadModel(
        title="Snap Session Test",
''',
)

replace_once(
    '''        title="Snap Session Test",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=sample_data["user"].id,
''',
    '''        title="Snap Session Test",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user_id,
''',
)

path.write_text(text)
