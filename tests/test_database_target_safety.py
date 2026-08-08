"""Tests for fail-closed database target validation."""

import pytest

from scripts.database_target_safety import require_local_database_url


@pytest.mark.parametrize(
    "db_url",
    [
        "postgresql://user:pass@localhost:5432/comic_pile",
        "postgresql+asyncpg://user:pass@127.0.0.1:5432/comic_pile",
        "postgres://user:pass@[::1]:5432/comic_pile",
        "postgresql://user:pass@127.42.1.9:5432/comic_pile",
    ],
)
def test_require_local_database_url_accepts_loopback(db_url: str) -> None:
    """Allow hostnames and addresses that are provably loopback.

    Args:
        db_url: Local PostgreSQL URL under test.

    Returns:
        None.
    """
    require_local_database_url(db_url)


@pytest.mark.parametrize(
    "db_url",
    [
        "postgresql://user:pass@ep-example.us-east-2.aws.neon.tech/comic_pile",
        "postgresql://user:pass@10.0.0.8/comic_pile",
        "postgresql://user:pass@192.168.1.20/comic_pile",
        "postgresql://user:pass@8.8.8.8/comic_pile",
        "postgresql:///comic_pile",
        "not-a-database-url",
    ],
)
def test_require_local_database_url_rejects_unproven_targets(db_url: str) -> None:
    """Fail closed for remote, LAN, and malformed database targets.

    Args:
        db_url: Unsafe or unprovable PostgreSQL URL under test.

    Returns:
        None.
    """
    with pytest.raises(ValueError, match="refusing to write"):
        require_local_database_url(db_url)
