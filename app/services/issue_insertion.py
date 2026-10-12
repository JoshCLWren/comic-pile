"""Shared issue insertion utilities.

This module contains the natural-order insertion logic shared between
the issue creation path, CBL adoption, and provider issue adoption to
avoid circular imports.
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue
from app.repositories import issue_repository
from app.utils.issue_natural_order import natural_issue_order

logger = logging.getLogger(__name__)


async def _insert_new_issues_in_natural_order(
    db: AsyncSession,
    thread_id: int,
    new_issue_numbers: list[str],
    natural_order: list[str],
) -> list[Issue]:
    """Create new issues at their natural position in the thread order.

    Existing issues whose position changes are re-seated through the same
    ``Issue.position`` column the thread reorder path writes, so no second
    ordering field, dependency edge, or Reading Plan node is introduced. Only
    ``position`` is assigned, which leaves read state, ratings, reading history,
    ComicVine identities, dependencies, and plan membership untouched.

    Args:
        db: Database session.
        thread_id: Thread receiving the new issues.
        new_issue_numbers: Issue numbers to create.
        natural_order: Every issue number of the resulting thread in ascending
            natural order.

    Returns:
        The newly created issues, ordered by their persisted position.
    """
    target_positions = {
        issue_number: position
        for position, issue_number in enumerate(natural_order, start=1)
    }

    existing_issues = await issue_repository.locked_issues(db, thread_id)
    shifted_issues = [
        issue
        for issue in existing_issues
        if issue.issue_number in target_positions
        and target_positions[issue.issue_number] != issue.position
    ]

    if shifted_issues:
        await issue_repository.defer_position_unique_constraint(db)
        for issue in shifted_issues:
            issue.position = target_positions[issue.issue_number]

    new_issues: list[Issue] = []
    for issue_number in new_issue_numbers:
        issue = Issue(
            thread_id=thread_id,
            issue_number=issue_number,
            position=target_positions[issue_number],
            status="unread",
        )
        await issue_repository.add_issue(db, issue)
        new_issues.append(issue)

    new_issues.sort(key=lambda created_issue: created_issue.position)

    return new_issues


async def create_issues_in_natural_order(
    db: AsyncSession,
    thread_id: int,
    issue_numbers: list[str],
) -> list[Issue] | None:
    """Create unread issues through the shared natural-order path.

    Args:
        db: Database session.
        thread_id: Thread receiving the issues.
        issue_numbers: Issue numbers to create, already filtered against the
            existing numbers.

    Returns:
        The newly created issues in persisted position order, or ``None`` when
        automatic placement is ambiguous (irregular numbering) and the caller
        must preserve the existing canonical order.
    """
    if not issue_numbers:
        return []

    existing_rows = await issue_repository.locked_issue_rows(db, thread_id)
    existing_issue_numbers = [row[1] for row in existing_rows]
    natural_order = natural_issue_order(existing_issue_numbers, issue_numbers)
    if natural_order is None:
        return None

    created = await _insert_new_issues_in_natural_order(
        db, thread_id, issue_numbers, natural_order
    )
    await db.flush()
    return created


async def create_issue_in_natural_order(
    db: AsyncSession,
    thread_id: int,
    issue_number: str,
) -> Issue:
    """Create one unread issue through the existing natural-order path.

    When automatic placement is ambiguous (irregular numbering), the issue is
    appended after the current last position, mirroring the append-only
    fallback of the issue creation path.

    Args:
        db: Database session.
        thread_id: Thread receiving the issue.
        issue_number: ComicVine issue number, stored verbatim.

    Returns:
        The newly created issue.
    """
    created = await create_issues_in_natural_order(db, thread_id, [issue_number])
    if created is not None:
        return created[0]

    existing_rows = await issue_repository.locked_issue_rows(db, thread_id)
    next_position = max((row[2] for row in existing_rows), default=0) + 1
    issue = Issue(
        thread_id=thread_id,
        issue_number=issue_number,
        position=next_position,
        status="unread",
    )
    await issue_repository.add_issue(db, issue)
    await db.flush()
    return issue
