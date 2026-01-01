"""Settings model for configurable application settings."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Settings(Base):
    """Settings model for configurable application settings."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_gap_hours: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    start_die: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    rating_min: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    rating_max: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    rating_step: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    rating_threshold: Mapped[float] = mapped_column(Float, default=4.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
