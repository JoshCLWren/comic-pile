"""Tests for bounded user-scoped cache generation primitives."""

from types import SimpleNamespace

import pytest

from app.cache_generation import (
    CacheCommandBudget,
    generation_key,
    namespaced_cache_key,
    user_id_from_arguments,
)


def test_generation_key_is_user_scoped() -> None:
    """Generation counters must be deterministic and isolated per user."""
    assert generation_key(7) == "cache:generation:user:7"
    assert generation_key(8) == "cache:generation:user:8"


def test_generation_key_rejects_invalid_user() -> None:
    """Invalid user identifiers must not create shared cache namespaces."""
    with pytest.raises(ValueError, match="user_id must be positive"):
        generation_key(0)


def test_namespaced_cache_key_changes_with_generation() -> None:
    """A generation bump must make every prior logical key unreachable."""
    first = namespaced_cache_key(7, 2, "cache:list_threads:User:7:")
    second = namespaced_cache_key(7, 3, "cache:list_threads:User:7:")

    assert first == "cache:user:7:g2:list_threads:User:7:"
    assert second == "cache:user:7:g3:list_threads:User:7:"
    assert first != second


def test_namespaced_cache_keys_are_isolated_between_users() -> None:
    """Two users must never share a generation-scoped value key."""
    first = namespaced_cache_key(7, 4, "cache:list_threads:")
    second = namespaced_cache_key(8, 4, "cache:list_threads:")

    assert first != second


def test_user_id_from_arguments_supports_current_cache_signatures() -> None:
    """Cached functions can expose ownership as an ID or user model argument."""
    user = SimpleNamespace(id=42)

    assert user_id_from_arguments({"user_id": 41}) == 41
    assert user_id_from_arguments({"user": user}) == 42
    assert user_id_from_arguments({"current_user": user}) == 42
    assert user_id_from_arguments({"thread_id": 99}) is None


def test_command_budget_counts_only_commands() -> None:
    """Instrumentation tracks command totals without needing cache-key contents."""
    budget = CacheCommandBudget()

    budget.record("generation_get")
    budget.record("value_get")
    budget.record("value_set", 2)

    assert budget.total == 4
    assert budget.counts == {
        "generation_get": 1,
        "value_get": 1,
        "value_set": 2,
    }


def test_command_budget_rejects_negative_counts() -> None:
    """Instrumentation must not permit impossible negative command totals."""
    budget = CacheCommandBudget()

    with pytest.raises(ValueError, match="cannot be negative"):
        budget.record("value_get", -1)
