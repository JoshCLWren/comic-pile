"""Unit tests for the destructive-test database guard in conftest."""

import pytest

from tests.conftest import assert_safe_test_database_url, get_test_database_url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://postgres:pw@127.0.0.1:5432/comic_pile_test",
        "postgresql+asyncpg://u:p@localhost/native_test",
        "sqlite+aiosqlite:///test.db",
    ],
)
def test_guard_accepts_local_test_databases(url: str) -> None:
    """Local test databases pass the guard."""
    assert_safe_test_database_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://u:p@example.neon.tech/neondb",
        "postgresql+asyncpg://u:p@example.neon.tech/comic_pile_test",
        "postgresql+asyncpg://u:p@127.0.0.1/neondb",
        "postgresql+asyncpg://u:p@localhost/dev",
        "postgresql+asyncpg://u:p@localhost/native_test?database=production",
        "postgresql+asyncpg://u:p@localhost/native_test?dbname=production",
    ],
)
def test_guard_refuses_remote_or_non_test_databases(url: str) -> None:
    """Remote hosts and non-test names are refused."""
    with pytest.raises(RuntimeError, match="Refusing"):
        assert_safe_test_database_url(url)


def test_get_test_database_url_ignores_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """DATABASE_URL never selects the test database."""
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@example.neon.tech/neondb")
    assert get_test_database_url().startswith("sqlite")


def test_get_test_database_url_refuses_unsafe_test_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unsafe TEST_DATABASE_URL is refused."""
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+asyncpg://u:p@example.neon.tech/neondb")
    with pytest.raises(RuntimeError, match="Refusing"):
        get_test_database_url()
