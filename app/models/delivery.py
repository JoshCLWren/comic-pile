"""Database-backed delivery ledger for cross-repository factory delivery."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DeliveryRecord(Base):
    """One cross-repository delivery record tracking factory work delivered to a target repo.

    The source repository (coordination repo) is always ComicPile. The target repository
    is the allowlisted delivery destination (e.g. Latticery). This model ensures that
    delivery identity is repository-safe and never confuses same-number issues/PRs
    across repositories.
    """

    __tablename__ = "delivery_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_repository: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    target_repository: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    target_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    target_pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_merge_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    worker_id: Mapped[str] = mapped_column(String(100), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'branch_created', 'pr_opened', 'merged', 'failed', 'released')",
            name="ck_delivery_status",
        ),
        CheckConstraint(
            "target_repository IN ('JoshCLWren/comic-pile', 'JoshCLWren/Latticery')",
            name="ck_delivery_target_repo",
        ),
    )

    @property
    def is_repo_safe_identity(self) -> str:
        """Return a repository-safe identity string for this delivery."""
        return f"{self.target_repository}#{self.id}"

    @property
    def delivery_key(self) -> str:
        """Return the unique delivery key combining target repo and issue/branch."""
        if self.issue_number is not None:
            return f"{self.target_repository}/issue-{self.issue_number}"
        return f"{self.target_repository}/branch-{self.target_branch}"
