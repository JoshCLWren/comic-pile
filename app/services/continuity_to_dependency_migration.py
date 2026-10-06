"""Migrate proven ContinuityRule semantics to canonical Dependencies."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContinuityRule
from app.repositories import dependency_repository

async def migrate_continuity_rules_to_dependencies(user_id: int, db: AsyncSession) -> int:
    """
    Convert proven hard ContinuityRule semantics into canonical issue-to-issue Dependencies.
    
    Target semantics:
    1. satisfaction_type == 'item_read' and source_type == 'issue' and target_type == 'issue'.
    2. satisfaction_type == 'converged' with targets of type 'issue'.
    
    Returns:
        Number of dependencies created.
    """
    # 1. Handle item_read (issue -> issue)
    rules_item_read = await db.execute(
        select(ContinuityRule).where(
            ContinuityRule.user_id == user_id,
            ContinuityRule.satisfaction_type == "item_read",
            ContinuityRule.source_type == "issue",
            ContinuityRule.target_type == "issue",
        )
    )
    
    created_count = 0
    for rule in rules_item_read.scalars():
        try:
            await dependency_repository.create_dependency(
                db, 
                source_issue_id=rule.source_id, 
                target_issue_id=rule.target_id
            )
            created_count += 1
        except Exception:
            # IntegrityError (duplicate) or others - we can ignore since we want the edge to exist
            pass

    # 2. Handle converged (multiple issue sources -> target)
    rules_converged = await db.execute(
        select(ContinuityRule).where(
            ContinuityRule.user_id == user_id,
            ContinuityRule.satisfaction_type == "converged",
            ContinuityRule.target_type == "issue",
        )
    )
    
    for rule in rules_converged.scalars():
        if rule.convergence_targets is None:
            continue
            
        for target_info in rule.convergence_targets:
            if isinstance(target_info, dict) and target_info.get("type") == "issue":
                source_issue_id = target_info.get("id")
                if source_issue_id is not None:
                    try:
                        await dependency_repository.create_dependency(
                            db, 
                            source_issue_id=int(source_issue_id), 
                            target_issue_id=rule.target_id
                        )
                        created_count += 1
                    except Exception:
                        pass
                        
    return created_count
