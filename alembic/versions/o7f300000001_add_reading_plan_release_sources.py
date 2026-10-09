"""Add reading_plan_release_sources for #3116.

Revision ID: o7f300000001
Revises: n6e300000001
Create Date: 2026-10-09 00:00:00.000000

Adds ``reading_plan_release_sources``: the durable reader follow-intent
record that a specific confirmed ComicVine volume should continue feeding
newly released issues into a specific existing Thread **for a specific
Reading Plan** (#3116).

The subscription is unique per (plan, thread, provider-volume) so repeated
writes converge instead of duplicating. Disabling a source is opt-in and
non-destructive: it only stops future discovery; already adopted Issues,
plan membership, read state, and dependencies are never touched by this
table's lifecycle (they cascade only through the plan/thread FKs when those
parents are deleted, which is unrelated to subscription disablement).
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "o7f300000001"
down_revision: str | Sequence[str] | None = "n6e300000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the release-source subscription table."""
    op.create_table(
        "reading_plan_release_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("continuity_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "external_identity_id",
            sa.Integer(),
            sa.ForeignKey("external_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_reading_plan_release_source",
        "reading_plan_release_sources",
        ["plan_id", "thread_id", "external_identity_id"],
    )
    op.create_index(
        "ix_reading_plan_release_sources_plan_id",
        "reading_plan_release_sources",
        ["plan_id"],
    )
    op.create_index(
        "ix_reading_plan_release_sources_thread_id",
        "reading_plan_release_sources",
        ["thread_id"],
    )
    op.create_index(
        "ix_reading_plan_release_sources_external_id",
        "reading_plan_release_sources",
        ["external_identity_id"],
    )
    op.create_index(
        "ix_reading_plan_release_sources_enabled_lookup",
        "reading_plan_release_sources",
        ["plan_id", "enabled"],
    )


def downgrade() -> None:
    """Drop the release-source subscription table."""
    op.drop_index(
        "ix_reading_plan_release_sources_enabled_lookup",
        table_name="reading_plan_release_sources",
    )
    op.drop_index(
        "ix_reading_plan_release_sources_external_id",
        table_name="reading_plan_release_sources",
    )
    op.drop_index(
        "ix_reading_plan_release_sources_thread_id",
        table_name="reading_plan_release_sources",
    )
    op.drop_index(
        "ix_reading_plan_release_sources_plan_id",
        table_name="reading_plan_release_sources",
    )
    op.drop_constraint(
        "uq_reading_plan_release_source",
        table_name="reading_plan_release_sources",
        type_="unique",
    )
    op.drop_table("reading_plan_release_sources")