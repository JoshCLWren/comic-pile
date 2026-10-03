"""Tag query construction and persistence.

All SQLAlchemy access for the ``Tag`` and ``TagAssignment`` models lives here.
Functions return ORM models or plain values; callers (services) own
transactions and authorization.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tag, TagAssignment


def _levenshtein(a: str, b: str) -> int:
    """Compute the Levenshtein edit distance between two strings.

    Args:
        a: The first string.
        b: The second string.

    Returns:
        The minimum number of single-character edits (insertions, deletions,
        or substitutions) required to transform ``a`` into ``b``.
    """
    if len(a) < len(b):
        return _levenshtein(b, a)

    if len(b) == 0:
        return len(a)

    previous_row: list[int] = list(range(len(b) + 1))
    for i, char_a in enumerate(a):
        current_row: list[int] = [i + 1]
        for j, char_b in enumerate(b):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (char_a != char_b)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


async def get_tag_by_id(db: AsyncSession, tag_id: int) -> Tag | None:
    """Return a tag by primary key.

    Args:
        db: Database session.
        tag_id: Primary key of the tag.

    Returns:
        The tag, or ``None`` when it does not exist.
    """
    return await db.get(Tag, tag_id)


async def get_tag_by_name(db: AsyncSession, normalized_name: str, scope: str) -> Tag | None:
    """Return a tag by normalized name and scope.

    Args:
        db: Database session.
        normalized_name: Lowercased, trimmed tag name.
        scope: Either ``"global"`` or ``"private"``.

    Returns:
        The tag, or ``None`` when it does not exist.
    """
    result = await db.execute(
        select(Tag).where(
            Tag.normalized_name == normalized_name,
            Tag.scope == scope,
        )
    )
    return result.scalar_one_or_none()


async def get_tag_by_normalized_name(db: AsyncSession, normalized_name: str) -> list[Tag]:
    """Return all tags matching a normalized name across both scopes.

    Args:
        db: Database session.
        normalized_name: Lowercased, trimmed tag name.

    Returns:
        List of matching tags (global and private).
    """
    result = await db.execute(
        select(Tag).where(Tag.normalized_name == normalized_name)
    )
    return list(result.scalars().all())


async def list_tags_for_user(db: AsyncSession, user_id: int) -> list[Tag]:
    """Return global tags plus the private tags owned by a user.

    Args:
        db: Database session.
        user_id: Owner of private tags to include.

    Returns:
        List of tags visible to the user.
    """
    result = await db.execute(
        select(Tag).where(
            (Tag.scope == "global") | (Tag.owner_user_id == user_id),
        )
        .order_by(Tag.scope.desc(), Tag.normalized_name)
    )
    return list(result.scalars().all())


async def list_global_tags(db: AsyncSession) -> list[Tag]:
    """Return all global tags, ordered for consistent display.

    Args:
        db: Database session.

    Returns:
        List of global tags.
    """
    result = await db.execute(
        select(Tag).where(Tag.scope == "global").order_by(Tag.normalized_name)
    )
    return list(result.scalars().all())


async def list_assignments_for_tag(db: AsyncSession, tag_id: int) -> list[TagAssignment]:
    """Return all assignments of a tag.

    Args:
        db: Database session.
        tag_id: Primary key of the tag.

    Returns:
        List of tag assignments.
    """
    result = await db.execute(
        select(TagAssignment).where(TagAssignment.tag_id == tag_id)
    )
    return list(result.scalars().all())


async def count_assignments_for_tag(db: AsyncSession, tag_id: int) -> int:
    """Return the number of assignments of a tag.

    Args:
        db: Database session.
        tag_id: Primary key of the tag.

    Returns:
        Number of assignments.
    """
    result = await db.execute(
        select(func.count(TagAssignment.id)).where(TagAssignment.tag_id == tag_id)
    )
    return result.scalar_one()


async def count_assignments_for_tag_by_target_type(
    db: AsyncSession, tag_id: int
) -> dict[str, int]:
    """Return assignment counts for a tag grouped by target type.

    Args:
        db: Database session.
        tag_id: Primary key of the tag.

    Returns:
        Map from target type to assignment count.
    """
    result = await db.execute(
        select(
            TagAssignment.target_type,
            func.count(TagAssignment.id).label("count"),
        )
        .where(TagAssignment.tag_id == tag_id)
        .group_by(TagAssignment.target_type)
    )
    return {row.target_type: row.count for row in result.all()}


async def has_assignment(
    db: AsyncSession, tag_id: int, target_type: str, target_id: int
) -> bool:
    """Return whether a tag is already assigned to a target.

    Args:
        db: Database session.
        tag_id: Primary key of the tag.
        target_type: Type of the target.
        target_id: Primary key of the target.

    Returns:
        ``True`` when the assignment already exists.
    """
    result = await db.execute(
        select(TagAssignment).where(
            TagAssignment.tag_id == tag_id,
            TagAssignment.target_type == target_type,
            TagAssignment.target_id == target_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def create_tag(db: AsyncSession, tag: Tag) -> Tag:
    """Persist a new tag.

    Args:
        db: Database session.
        tag: Tag to persist.

    Returns:
        The persisted tag.
    """
    db.add(tag)
    await db.flush()
    await db.refresh(tag)
    return tag


async def update_tag(db: AsyncSession, tag: Tag) -> Tag:
    """Persist changes to an existing tag.

    Args:
        db: Database session.
        tag: Tag to persist.

    Returns:
        The persisted tag.
    """
    db.add(tag)
    await db.flush()
    await db.refresh(tag)
    return tag


async def assign_tag(db: AsyncSession, tag_id: int, target_type: str, target_id: int) -> int | None:
    """Insert an assignment if one does not already exist.

    Args:
        db: Database session.
        tag_id: Primary key of the tag.
        target_type: Type of the target.
        target_id: Primary key of the target.

    Returns:
        The new assignment primary key, or ``None`` when the assignment
        already exists (idempotent).
    """
    existing = await has_assignment(db, tag_id, target_type, target_id)
    if existing:
        return None

    result = await db.execute(
        select(TagAssignment).where(
            TagAssignment.tag_id == tag_id,
            TagAssignment.target_type == target_type,
            TagAssignment.target_id == target_id,
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment is not None:
        return assignment.id

    assignment = TagAssignment(
        tag_id=tag_id,
        target_type=target_type,
        target_id=target_id,
    )
    db.add(assignment)
    await db.flush()
    await db.refresh(assignment)
    return assignment.id


async def unassign_tag(
    db: AsyncSession, tag_id: int, target_type: str, target_id: int
) -> int:
    """Remove one assignment and return how many rows were affected.

    Args:
        db: Database session.
        tag_id: Primary key of the tag.
        target_type: Type of the target.
        target_id: Primary key of the target.

    Returns:
        Number of assignments removed (0 or 1).
    """
    result = await db.execute(
        select(TagAssignment).where(
            TagAssignment.tag_id == tag_id,
            TagAssignment.target_type == target_type,
            TagAssignment.target_id == target_id,
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        return 0

    await db.delete(assignment)
    return 1


async def delete_tag_assignments(db: AsyncSession, tag_id: int) -> int:
    """Delete all assignments of a tag and return how many were removed.

    Args:
        db: Database session.
        tag_id: Primary key of the tag.

    Returns:
        Number of assignments removed.
    """
    result = await db.execute(
        select(TagAssignment).where(TagAssignment.tag_id == tag_id)
    )
    assignment_ids: list[int] = [a.id for a in result.scalars().all()]
    if not assignment_ids:
        return 0

    await db.execute(
        select(TagAssignment).where(TagAssignment.id.in_(assignment_ids))
        .execution_options(synchronize_session=False)
    )
    count = len(assignment_ids)
    await db.execute(
        delete(TagAssignment).where(TagAssignment.id.in_(assignment_ids))
    )
    return count


async def find_nearly_matching_global_tags(
    db: AsyncSession,
    normalized_name: str,
    *,
    max_distance: int,
    limit: int,
) -> list[Tag]:
    """Return global tags whose normalized name is a near match.

    A target is a near match when the Levenshtein distance is at most
    ``max_distance`` or one normalized name is a substring of the other.

    Args:
        db: Database session.
        normalized_name: Lowercased, trimmed name to compare against.
        max_distance: Maximum Levenshtein distance for a match.
        limit: Maximum number of matches to return.

    Returns:
        List of matching global tags.
    """
    global_tags = await list_global_tags(db)

    matches: list[Tag] = []
    for tag in global_tags:
        tag_name = tag.normalized_name
        distance = _levenshtein(normalized_name, tag_name)
        if distance <= max_distance:
            matches.append((distance, tag))
            continue
        if normalized_name in tag_name or tag_name in normalized_name:
            matches.append((distance, tag))

    matches.sort(key=lambda item: item[0])
    return [tag for _distance, tag in matches[:limit]]


async def get_tag_with_counts(
    db: AsyncSession, tag_id: int
) -> tuple[Tag, int, dict[str, int]]:
    """Fetch a tag together with its assignment totals.

    Args:
        db: Database session.
        tag_id: Primary key of the tag.

    Returns:
        Tuple of ``(tag, total_count, counts_by_target_type)``.
    """
    tag = await get_tag_by_id(db, tag_id)
    if tag is None:
        return tag, 0, {}  # type: ignore[return-value]

    total = await count_assignments_for_tag(db, tag_id)
    by_type = await count_assignments_for_tag_by_target_type(db, tag_id)
    return tag, total, by_type
