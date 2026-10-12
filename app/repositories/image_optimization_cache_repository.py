"""Repository for image optimization cache."""

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.image_optimization_cache import ImageOptimizationCache


class ImageOptimizationCacheRepository:
    """Repository for image optimization cache operations."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self, cache_key: str) -> Optional[ImageOptimizationCache]:
        """Get a cached optimized image by cache key."""
        stmt = select(ImageOptimizationCache).where(
            ImageOptimizationCache.cache_key == cache_key,
            ImageOptimizationCache.expires_at > datetime.now(UTC),
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def set(
        self,
        cache_key: str,
        source_url: str,
        width: int,
        content: bytes,
        media_type: str,
        transcoded: bool,
        ttl_seconds: int = 31536000,  # 1 year default
    ) -> ImageOptimizationCache:
        """Store an optimized image in the cache."""
        expires_at = datetime.now(UTC).replace(
            microsecond=0
        )  # Expires at end of TTL
        # We'll set expires_at using the TTL
        from datetime import timedelta

        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)

        cache_entry = ImageOptimizationCache(
            cache_key=cache_key,
            source_url=source_url,
            width=width,
            content=content,
            media_type=media_type,
            transcoded=transcoded,
            content_length=len(content),
            expires_at=expires_at,
        )
        self._db.add(cache_entry)
        await self._db.flush()
        return cache_entry

    async def delete_expired(self) -> int:
        """Delete expired cache entries. Returns count of deleted entries."""
        stmt = delete(ImageOptimizationCache).where(
            ImageOptimizationCache.expires_at <= datetime.now(UTC)
        )
        result = await self._db.execute(stmt)
        return result.rowcount