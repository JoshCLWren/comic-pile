"""Performance metric model for tracking production startup and page-load metrics."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PerformanceMetric(Base):
    """Performance metric recorded from production requests.

    Stores timing measurements and cold/warm classification for representative
    flows so that regressions can be tied to deployments and distinguished from
    isolated provider delays.

    __tablename__ = "performance_metrics"
    """

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    deployment_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    request_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    metric_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    cold: Mapped[bool] = mapped_column(
        nullable=False,
        index=True,
    )
    response_time_ms: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    success: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_perf_metric_type_cold", "metric_type", "cold"),
        Index("ix_perf_metric_timestamp", "timestamp"),
    )