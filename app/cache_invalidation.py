"""Bounded cache invalidation helpers for mutation paths.

Production invalidation must never traverse the Redis keyspace. This module gives
mutation code one user-scoped invalidation boundary backed by the generation
primitive from :mod:`app.cache_generation`.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.cache_generation import invalidate_user_cache, invalidate_user_caches


async def invalidate_user_view(user_id: int) -> bool:
    """Invalidate every cached view owned by one user with one generation bump.

    Args:
        user_id: Authenticated user identifier.

    Returns:
        ``True`` when the generation was bumped, otherwise ``False`` when caching
        is disabled or unavailable.
    """
    if user_id <= 0:
        raise ValueError("user_id must be positive")
    return await invalidate_user_cache(user_id)


async def invalidate_user_views(user_ids: Iterable[int]) -> int:
    """Invalidate each distinct user namespace at most once.

    Args:
        user_ids: User identifiers affected by one logical mutation batch.

    Returns:
        Number of user namespaces successfully invalidated.
    """
    normalized = tuple(user_ids)
    if any(user_id <= 0 for user_id in normalized):
        raise ValueError("user_id must be positive")
    return await invalidate_user_caches(normalized)
