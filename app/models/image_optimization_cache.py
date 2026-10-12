"""Image optimization cache model."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ImageOptimizationCache(Base):
    """Cached optimized image for fast repeat delivery."""

    __tablename__ = "image_optimization_cache"

    cache_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    width: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    content: Mapped[bytes] = mapped_column(BYTEA(), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    transcoded: Mapped[bool] = mapped_column(nullable=False)
    content_length: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    def __repr__(self) -> str:
        """Return a string representation of the cache entry."""
        return f"<ImageOptimizationCache(key={self.cache_key[:32]}..., width={self.width})>"