"""FailedLoginAttempt model for database."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FailedLoginAttempt(Base):
    """Record of a failed login attempt for lockout tracking."""

    __tablename__ = "failed_login_attempts"
    __table_args__ = (
        Index("ix_failed_login_username_time", "username", "attempted_at"),
        Index("ix_failed_login_ip_time", "ip_address", "attempted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
