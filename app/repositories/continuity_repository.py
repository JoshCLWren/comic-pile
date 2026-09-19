"""Continuity plan and rule query construction and persistence.

All SQLAlchemy access for the ``ContinuityPlan``/``ContinuityRule`` model
family lives here. Functions return ORM models or row counts; callers
(services) own transactions.
"""

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.issue import Issue
from app.models.thread import Thread


async def plans_for_user(db: AsyncSession, user_id: int) -> list[ContinuityPlan]:
    """List every continuity plan owned by a user.

    Args:
        db: Database session.
        user_id: Owner of the plans.

    Returns:
        The user's plans in primary-key order.
    """
    result = await db.execute(select(ContinuityPlan).where(ContinuityPlan.user_id == user_id))
    return list(result.scalars().all())


async def delete_plan_rules_referencing_issues(
    db: AsyncSession, user_id: int, marker: str, issue_ids: set[int]
) -> None:
    """Delete plan-owned rules whose source or target references deleted issues.

    Args:
        db: Database session.
        user_id: Owner of the rules.
        marker: Ownership note marking rules that belong to one plan.
        issue_ids: Issue primary keys considered deleted.
    """
    await db.execute(
        delete(ContinuityRule).where(
            ContinuityRule.user_id == user_id,
            ContinuityRule.note == marker,
            (
                (ContinuityRule.source_type == "issue")
                & (ContinuityRule.source_id.in_(issue_ids))
            )
            | ((ContinuityRule.target_type == "issue") & (ContinuityRule.target_id.in_(issue_ids))),
        )
    )


async def delete_rules_for_marker(db: AsyncSession, user_id: int, marker: str) -> None:
    """Delete every rule owned by one plan via its ownership marker note.

    Args:
        db: Database session.
        user_id: Owner of the rules.
        marker: Ownership note marking rules that belong to one plan.
    """
    await db.execute(
        delete(ContinuityRule).where(
            ContinuityRule.user_id == user_id,
            ContinuityRule.note == marker,
        )
    )


async def rules_for_user(db: AsyncSession, user_id: int) -> list[ContinuityRule]:
    """List every continuity rule owned by a user, ordered by identifier."""
    result = await db.execute(
        select(ContinuityRule)
        .options(selectinload(ContinuityRule.selected_members))
        .where(ContinuityRule.user_id == user_id)
        .order_by(ContinuityRule.id)
    )
    return list(result.scalars().all())


async def get_continuity_rule(
    db: AsyncSession, user_id: int, rule_id: int
) -> ContinuityRule | None:
    """Load one owned continuity rule with selected members."""
    result = await db.execute(
        select(ContinuityRule)
        .options(selectinload(ContinuityRule.selected_members))
        .where(ContinuityRule.id == rule_id, ContinuityRule.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_continuity_plan(
    db: AsyncSession, user_id: int, plan_id: int
) -> ContinuityPlan | None:
    """Load one owned continuity plan."""
    result = await db.execute(
        select(ContinuityPlan).where(
            ContinuityPlan.id == plan_id, ContinuityPlan.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def delete_continuity_plan_rules_for_marker(
    db: AsyncSession, user_id: int, marker: str
) -> None:
    """Delete every rule owned by one plan via its ownership marker."""
    await delete_rules_for_marker(db, user_id=user_id, marker=marker)


CONTINUITY_LOCK_NAMESPACE = 1_129_274_964


async def owned_issue_ids_for_user(
    db: AsyncSession, user_id: int, issue_ids: list[int]
) -> set[int]:
    """Return the subset of issue IDs owned by the user."""
    result = await db.execute(
        select(Issue.id)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id.in_(issue_ids), Thread.user_id == user_id)
    )
    return set(result.scalars())


async def lock_continuity_graph(db: AsyncSession, user_id: int) -> None:
    """Serialize continuity graph mutations for one user."""
    await db.execute(
        select(func.pg_advisory_xact_lock(CONTINUITY_LOCK_NAMESPACE, user_id)),
    )


async def delete_rules_referencing_issues(
    db: AsyncSession, user_id: int, issue_ids: set[int]
) -> None:
    """Delete any rule (plan-owned or not) referencing deleted issues.

    Args:
        db: Database session.
        user_id: Owner of the rules.
        issue_ids: Issue primary keys considered deleted.
    """
    await db.execute(
        delete(ContinuityRule).where(
            ContinuityRule.user_id == user_id,
            (
                (ContinuityRule.source_type == "issue")
                & (ContinuityRule.source_id.in_(issue_ids))
            )
            | ((ContinuityRule.target_type == "issue") & (ContinuityRule.target_id.in_(issue_ids))),
        )
    )
