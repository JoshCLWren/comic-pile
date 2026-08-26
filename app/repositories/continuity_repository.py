"""Continuity plan and rule query construction and persistence.

All SQLAlchemy access for the ``ContinuityPlan``/``ContinuityRule`` model
family lives here. Functions return ORM models or row counts; callers
(services) own transactions.
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule


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
