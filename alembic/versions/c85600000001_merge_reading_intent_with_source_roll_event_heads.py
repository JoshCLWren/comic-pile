"""Merge reading-intent and source-roll-event migration heads.

Revision ID: c85600000001
Revises: c85500000001, d4e5f6a7b8c9
Create Date: 2026-08-24 00:00:00.000000
"""

from collections.abc import Sequence

revision: str = "c85600000001"
down_revision: str | Sequence[str] | None = ("c85500000001", "d4e5f6a7b8c9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Reunify the branched migration history; no schema change."""


def downgrade() -> None:
    """Restore the two independent heads; no schema change."""
