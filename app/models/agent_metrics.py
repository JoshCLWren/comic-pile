"""AgentMetrics model for tracking Ralph orchestrator performance."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

if TYPE_CHECKING:
    pass


class AgentMetrics(Base):
    """Model for tracking Ralph agent task execution metrics."""

    __tablename__ = "agent_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    duration: Mapped[float] = mapped_column(Float, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_calls: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
