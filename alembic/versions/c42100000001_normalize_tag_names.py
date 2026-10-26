"""Collapse internal whitespace in stored tag matching keys (#4182).

Revision ID: c42100000001
Revises: c30740000001
Create Date: 2026-10-26

``normalize_tag_name`` used to trim and lowercase only, so a tag saved as
``Red  Label`` kept the key ``red  label`` while every new lookup asks for
``red label``. Full-name searches stopped matching those rows, and creating the
same display name again could insert a duplicate because the unique indexes
compare different stored keys.

This revision rewrites every stored ``normalized_name`` with the current
normalization. When two rows in the same uniqueness scope (global, or one
owner's private vocabulary) collapse to the same key, the oldest row survives:
its assignments absorb the duplicates' assignments, assignment rows that would
collide with an existing ``(tag_id, target_type, target_id)`` pair are dropped,
and the duplicate tag rows are deleted. No assignment is lost and no display
``name`` is rewritten.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "c42100000001"
down_revision: str | Sequence[str] | None = "c30740000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _normalize(name: str) -> str:
    """Return the current stored-key form of a tag name.

    Args:
        name: A stored (or previously normalized) tag name.

    Returns:
        The trimmed, whitespace-collapsed, lowercased key.
    """
    return " ".join(name.split()).lower()


def upgrade() -> None:
    """Rewrite stored tag keys and merge rows that collapse to one key."""
    bind = op.get_bind()
    rows = bind.execute(
        text(
            "SELECT id, scope, owner_user_id, normalized_name "
            "FROM tags ORDER BY created_at, id"
        )
    ).all()

    # Rows are ordered oldest-first, so each group's first id is the survivor
    # whose tag identity (name, color, scope, owner) is preserved.
    groups: dict[tuple[str, int | None, str], list[int]] = defaultdict(list)
    for tag_id, scope, owner_user_id, normalized_name in rows:
        groups[(scope, owner_user_id, _normalize(normalized_name))].append(int(tag_id))

    merged = 0
    moved_assignments = 0
    for (_, _, key), tag_ids in groups.items():
        survivor = tag_ids[0]
        for duplicate in tag_ids[1:]:
            moved_assignments += bind.execute(
                text(
                    "UPDATE tag_assignments "
                    "SET tag_id = :survivor "
                    "WHERE tag_id = :duplicate "
                    "AND NOT EXISTS ("
                    "SELECT 1 FROM tag_assignments AS keep "
                    "WHERE keep.tag_id = :survivor "
                    "AND keep.target_type = tag_assignments.target_type "
                    "AND keep.target_id = tag_assignments.target_id)"
                ),
                {"survivor": survivor, "duplicate": duplicate},
            ).rowcount or 0
            # Whatever is left already exists on the survivor (the unique
            # assignment index forbids the pair twice) and goes away with the
            # duplicate tag row.
            bind.execute(
                text("DELETE FROM tag_assignments WHERE tag_id = :duplicate"),
                {"duplicate": duplicate},
            )
            bind.execute(
                text("DELETE FROM tags WHERE id = :duplicate"),
                {"duplicate": duplicate},
            )
            merged += 1
        bind.execute(
            text(
                "UPDATE tags SET normalized_name = :key "
                "WHERE id = :survivor AND normalized_name <> :key"
            ),
            {"key": key, "survivor": survivor},
        )

    print(
        f"[c42100000001] normalized {len(rows)} tag key(s); "
        f"merged {merged} duplicate tag(s); "
        f"moved {moved_assignments} assignment(s)"
    )


def downgrade() -> None:
    """No-op: the previous stored keys and duplicate rows cannot be rebuilt.

    Collapsing whitespace discards the distinction between ``red  label`` and
    ``red label``, and merged duplicate tags are gone. Rolling the revision back
    leaves the normalized keys in place instead of inventing data.
    """
    return
