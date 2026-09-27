"""Service for converting continuity rules to canonical dependencies."""

from typing import TYPE_CHECKING

from sqlalchemy import select, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_rule import ContinuityRule, SATISFACTION_TYPES
from app.models.dependency import Dependency
from app.models.issue import Issue

if TYPE_CHECKING:
    from app.models.continuity_plan import ContinuityPlan


class ContinuityRuleDependencyService:
    """Service for converting continuity rules to canonical dependencies."""

    @staticmethod
    async def get_missing_dependencies_for_user(
        user_id: int, db: AsyncSession
    ) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
        """Get missing dependencies that need to be created from continuity rules.
        
        Returns:
            A tuple of (missing_item_read_edges, missing_converged_edges) where each
            edge is a (source_issue_id, target_issue_id) tuple.
        """
        # Get all existing dependency edges for this user
        existing_deps = await db.execute(
            select(Dependency.source_issue_id, Dependency.target_issue_id)
            .join(Issue, Issue.id == Dependency.source_issue_id)
            .where(Issue.user_id == user_id)
        )
        existing_edges = {(row.source_issue_id, row.target_issue_id) for row in existing_deps.all()}
        
        # Get rule-native item_read rules that don't have corresponding dependencies
        missing_item_read = await db.execute(
            select(ContinuityRule.source_id, ContinuityRule.target_id)
            .where(ContinuityRule.user_id == user_id)
            .where(ContinuityRule.satisfaction_type == "item_read")
            .where(ContinuityRule.source_type == "issue")
            .where(ContinuityRule.target_type == "issue")
            .where(
                select(select(Dependency.id).where(
                    (Dependency.source_issue_id == ContinuityRule.source_id) &
                    (Dependency.target_issue_id == ContinuityRule.target_id)
                )).scalar_subquery() is None
            )
        )
        missing_item_read_edges = {
            (row.source_id, row.target_id) for row in missing_item_read.all()
        }
        
        # Get converged rules that need to be expanded
        converged_rules = await db.execute(
            select(
                ContinuityRule.id,
                ContinuityRule.source_id,
                ContinuityRule.target_id,
                ContinuityRule.convergence_targets
            )
            .where(ContinuityRule.user_id == user_id)
            .where(ContinuityRule.satisfaction_type == "converged")
            .where(ContinuityRule.source_type == "issue")
            .where(ContinuityRule.target_type == "issue")
            .where(ContinuityRule.convergence_targets.isnot(None))
        )
        
        missing_converged_edges = set()
        for row in converged_rules.all():
            # Each converged rule expands to multiple source -> target edges
            for target in row.convergence_targets:
                if isinstance(target, dict) and target.get("type") == "issue":
                    target_id = target.get("id")
                    if target_id:
                        edge = (target_id, row.target_id)
                        if edge not in existing_edges:
                            missing_converged_edges.add(edge)
        
        return missing_item_read_edges, missing_converged_edges

    @staticmethod
    async def create_canonical_dependencies(
        user_id: int, db: AsyncSession
    ) -> tuple[int, int]:
        """Create the 942 canonical dependencies from continuity rules.
        
        Returns:
            A tuple of (item_read_count, converged_count) representing the
            number of dependencies created for each type.
        """
        missing_item_read, missing_converged = await ContinuityRuleDependencyService.get_missing_dependencies_for_user(
            user_id, db
        )
        
        # Create item_read dependencies
        item_read_count = 0
        if missing_item_read:
            # Validate that all issues exist and belong to the user
            issue_ids = set()
            for source_id, target_id in missing_item_read:
                issue_ids.add(source_id)
                issue_ids.add(target_id)
            
            # Check issue ownership
            issue_result = await db.execute(
                select(Issue.id)
                .where(Issue.user_id == user_id)
                .where(Issue.id.in_(issue_ids))
            )
            owned_issues = {row.id for row in issue_result.all()}
            
            # Only create dependencies for owned issues
            valid_item_read = []
            for source_id, target_id in missing_item_read:
                if source_id in owned_issues and target_id in owned_issues:
                    valid_item_read.append({"source_issue_id": source_id, "target_issue_id": target_id})
            
            if valid_item_read:
                await db.execute(
                    insert(Dependency),
                    valid_item_read
                )
                item_read_count = len(valid_item_read)
        
        # Create converged dependencies
        converged_count = 0
        if missing_converged:
            # Validate that all issues exist and belong to the user
            issue_ids = set()
            for source_id, target_id in missing_converged:
                issue_ids.add(source_id)
                issue_ids.add(target_id)
            
            # Check issue ownership
            issue_result = await db.execute(
                select(Issue.id)
                .where(Issue.user_id == user_id)
                .where(Issue.id.in_(issue_ids))
            )
            owned_issues = {row.id for row in issue_result.all()}
            
            # Only create dependencies for owned issues
            valid_converged = []
            for source_id, target_id in missing_converged:
                if source_id in owned_issues and target_id in owned_issues:
                    valid_converged.append({"source_issue_id": source_id, "target_issue_id": target_id})
            
            if valid_converged:
                await db.execute(
                    insert(Dependency),
                    valid_converged
                )
                converged_count = len(valid_converged)
        
        return item_read_count, converged_count

    @staticmethod
    async def validate_canonical_dependencies(user_id: int, db: AsyncSession) -> dict:
        """Validate that canonical dependencies are correctly created.
        
        Returns:
            A dictionary with validation results including counts and any issues.
        """
        # Get all canonical dependencies (excluding cbl-order:% rows)
        canonical_deps = await db.execute(
            select(Dependency)
            .join(Issue, Issue.id == Dependency.source_issue_id)
            .where(Issue.user_id == user_id)
            .where(
                (Dependency.note.is_(None)) | 
                (Dependency.note.notlike('cbl-order:%'))
            )
        )
        canonical_count = len(canonical_deps.all())
        
        # Get rule-native item_read rules
        item_read_rules = await db.execute(
            select(ContinuityRule)
            .where(ContinuityRule.user_id == user_id)
            .where(ContinuityRule.satisfaction_type == "item_read")
            .where(ContinuityRule.source_type == "issue")
            .where(ContinuityRule.target_type == "issue")
        )
        item_read_count = len(item_read_rules.all())
        
        # Get converged rules
        converged_rules = await db.execute(
            select(ContinuityRule)
            .where(ContinuityRule.user_id == user_id)
            .where(ContinuityRule.satisfaction_type == "converged")
            .where(ContinuityRule.source_type == "issue")
            .where(ContinuityRule.target_type == "issue")
            .where(ContinuityRule.convergence_targets.isnot(None))
        )
        converged_count = len(converged_rules.all())
        
        # Count actual edges from converged rules
        converged_edges = 0
        for rule in converged_rules.all():
            if rule.convergence_targets:
                for target in rule.convergence_targets:
                    if isinstance(target, dict) and target.get("type") == "issue":
                        converged_edges += 1
        
        return {
            "canonical_dependencies": canonical_count,
            "item_read_rules": item_read_count,
            "converged_rules": converged_count,
            "converged_edges": converged_edges,
            "total_canonical_edges": canonical_count,
        }