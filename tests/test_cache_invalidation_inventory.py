"""Tests for the cache invalidation inventory tool."""

from pathlib import Path

from scripts.cache_invalidation_inventory import build_inventory


def test_inventory_classifies_bounded_and_unbounded_calls(tmp_path: Path) -> None:
    """Inventory distinguishes generation bumps from wildcard invalidation."""
    source_root = tmp_path / "app"
    source_root.mkdir()
    (source_root / "sample.py").write_text(
        """
from app.cache import cached, invalidate_cache
from app.cache_generation import invalidate_user_cache

@cached()
async def get_widget(user_id: int):
    return user_id

async def mutate_widget(user_id: int):
    await invalidate_cache(f\"cache:get_widget:{user_id}:*\")
    await invalidate_user_cache(user_id)
""".strip()
        + "\n",
        encoding="utf-8",
    )

    inventory = build_inventory((source_root,))

    assert [(item.function, item.cache_kind) for item in inventory.cached_functions] == [
        ("get_widget", "cached")
    ]
    assert [
        (item.function, item.invalidation_kind, item.bounded)
        for item in inventory.invalidation_calls
    ] == [
        ("mutate_widget", "invalidate_cache", False),
        ("mutate_widget", "invalidate_user_cache", True),
    ]
    assert inventory.unbounded_invalidation_count == 1


def test_inventory_detects_method_clear_pattern_and_generation_decorator(tmp_path: Path) -> None:
    """Inventory recognizes method-form scans and generation-aware readers."""
    source_root = tmp_path / "comic_pile"
    source_root.mkdir()
    (source_root / "sample.py").write_text(
        """
from app.cache_generation import generation_cached

@generation_cached()
async def get_widget(current_user):
    return current_user.id

async def clear_widget(cache):
    await cache.clear_pattern(\"cache:*\")
""".strip()
        + "\n",
        encoding="utf-8",
    )

    inventory = build_inventory((source_root,))

    assert inventory.cached_functions[0].cache_kind == "generation_cached"
    assert inventory.invalidation_calls[0].invalidation_kind == "clear_pattern"
    assert inventory.invalidation_calls[0].bounded is False
