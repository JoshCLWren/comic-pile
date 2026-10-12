"""Image optimization cache query construction and persistence.

All SQLAlchemy access for the ``ImageOptimizationCache`` model family lives
here. Functions return ORM models or plain values; services own transactions
and error handling.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.image_optimization_cache import ImageOptimizationCache


class ImageOptimizationCacheRepository:
    """Repository for image optimization cache operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the repository with a database session.

        Args:
            db: Async database session.
        """
        self._db = db

    async def get(self, cache_key: str) -> ImageOptimizationCache | None:
        """Get an unexpired cached optimized image by cache key.

        Args:
            cache_key: Deterministic cache key for the optimized variant.

        Returns:
            The cache entry, or ``None`` when absent or expired.
        """
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
    ) -> None:
        """Store an optimized image, refreshing any row already held for the key.

        The write is an upsert rather than a plain insert. Reads filter out
        expired rows but never delete them, so an insert-only store can never
        replace an expired variant: every later request for that key would miss
        permanently and keep paying the upstream fetch and transcode. The upsert
        also resolves overlapping cold requests for the same key as an update
        instead of a unique violation.

        ``created_at`` is preserved on refresh so it keeps meaning when the row
        was first written; ``expires_at`` carries the freshness.

        Args:
            cache_key: Deterministic cache key for the optimized variant.
            source_url: Validated upstream image URL.
            width: Snapped variant width in pixels.
            content: Optimized image bytes to store.
            media_type: Media type of the stored bytes.
            transcoded: Whether the bytes were transcoded.
            ttl_seconds: Seconds until the entry expires.
        """
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        content_length = len(content)

        stmt = pg_insert(ImageOptimizationCache).values(
            cache_key=cache_key,
            source_url=source_url,
            width=width,
            content=content,
            media_type=media_type,
            transcoded=transcoded,
            content_length=content_length,
            created_at=now,
            expires_at=expires_at,
        )
        await self._db.execute(
            stmt.on_conflict_do_update(
                index_elements=[ImageOptimizationCache.__table__.c.cache_key],
                set_={
                    "source_url": source_url,
                    "width": width,
                    "content": content,
                    "media_type": media_type,
                    "transcoded": transcoded,
                    "content_length": content_length,
                    "expires_at": expires_at,
                },
            )
        )

    async def delete_expired(self) -> int:
        """Delete expired cache entries.

        Returns:
            Count of deleted entries.
        """
        stmt = delete(ImageOptimizationCache).where(
            ImageOptimizationCache.expires_at <= datetime.now(UTC)
        )
        result = await self._db.execute(stmt)
        return getattr(result, "rowcount", 0) or 0
