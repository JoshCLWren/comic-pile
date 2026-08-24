"""Merge c85500000001 and d4e5f6a7b8c9 heads.

Revision ID: merge_c855_d4e5
Revises: c85500000001, d4e5f6a7b8c9
Create Date: 2026-08-24 00:00:00.000000

"""
from collections.abc import Sequence


revision: str = "merge_c855_d4e5"
down_revision: str | Sequence[str] | None = ("c85500000001", "d4e5f6a7b8c9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge heads - no schema changes."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass