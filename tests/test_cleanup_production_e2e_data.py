"""Tests for the production E2E data janitor."""

import pytest

from scripts.cleanup_production_e2e_data import (
    cleanup_stale_threads,
    is_managed_e2e_title,
)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("[E2E] 12345-1 queue smoke", True),
        ("[E2E] run_20260806 thread edit", True),
        ("[E2E] run.with-dots dependency test", True),
        ("[E2E] missing-description", False),
        ("[E2E]  queue smoke", False),
        ("[e2e] 123 queue smoke", False),
        ("Josh's real thread", False),
        ("prefix [E2E] 123 queue smoke", False),
        ("[E2E] 123", False),
    ],
)
def test_is_managed_e2e_title_requires_strict_prefix_and_run_id(
    title: str,
    expected: bool,
) -> None:
    """Only unmistakably automation-owned titles are cleanup candidates."""
    assert is_managed_e2e_title(title) is expected


@pytest.mark.asyncio
async def test_cleanup_rejects_empty_account_before_database_access() -> None:
    """Cleanup cannot run without an exact dedicated-account boundary."""
    with pytest.raises(ValueError, match="account_email must not be empty"):
        await cleanup_stale_threads(account_email="   ")


@pytest.mark.asyncio
async def test_cleanup_rejects_nonpositive_age_before_database_access() -> None:
    """Cleanup cannot erase active or newly-created test records."""
    with pytest.raises(ValueError, match="max_age_hours must be at least 1"):
        await cleanup_stale_threads(
            account_email="automation@example.com",
            max_age_hours=0,
        )
