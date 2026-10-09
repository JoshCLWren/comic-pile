#!/usr/bin/env python3
"""Persist the 942 canonical Dependency edges from ContinuityRules.

This script reads ContinuityRule data and inserts the missing Dependency rows
required for the Roll cutover to canonical Dependency-only authority.

From the runtime audit (section 4.3):
  - 807 rule-native item_read rules need one Dependency row each
  - 130 converged rules expand to 135 Dependency edges (5 rules have 2 targets)

The new rows have ``note = NULL`` so they are part of the canonical set
(note IS NULL OR note NOT LIKE 'cbl-order:%') and exclude historical CBL
materialization rows.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_database_settings
from app.database import get_db
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency

logger = logging.getLogger(__name__)


async def _get_db_session() -> AsyncSession:
    """Get an async database session."""
    from app.database import engine
    async with AsyncSession(engine) as db:
        return db


async def persist_rule_native_item_read_edges() -> int:
    """Persist rule-native item_read rules as canonical Dependency rows.

    These are ContinuityRules with satisfaction_type = 'item_read',
    source_type = 'issue', and no existing Dependency row (legacy_dependency_id is NULL).

    Returns:
        Number of Dependency rows inserted.
    """
    db = await _get_db_session()
    try:
        # Find all rule-native item_read rules (source_type = 'issue', no legacy_dependency_id)
        result = await db.execute(
            select(ContinuityRule)
            .where(
                ContinuityRule.satisfaction_type == "item_read",
                ContinuityRule.source_type == "issue",
                ContinuityRule.legacy_dependency_id.is_(None),
            )  # noqa: E711  intentional: checking IS NULL vs is_(None)
        )
        # Actually, the above has a typo - let me fix this
        result = await db.execute(
            select(ContinuityRule)
            .where(
                ContinuityRule.satisfaction_type == "item_read",
                ContinuityRule.source_type == "issue",
                ContinuityRule.legacy_dependency_id.is_(None),  # noqa: E711
            )
        )
        rules = result.scalars().all()

        logger.info(f"Found {len(rules)} rule-native item_read ContinuityRules")

        inserted = 0
        for rule in rules:
            # Check if a Dependency row already exists for this edge
            existing = await db.execute(
                select(Dependency).where(
                    Dependency.source_issue_id == rule.source_id,
                    Dependency.target_issue_id == rule.target_id,
                )
            )
            if existing.scalar_one_or_none() is not None:
                # Dependency row already exists; skip
                continue

            # Insert new Dependency row with note = NULL (canonical set)
            new_dep = Dependency(
                source_issue_id=rule.source_id,
                target_issue_id=rule.target_id,
                # note stays NULL by default
            )
            db.add(new_dep)
            inserted += 1

        if inserted > 0:
            await db.commit()
        logger.info(f"Inserted {inserted} rule-native item_read Dependency rows")
        return inserted
    finally:
        await db.close()


async def persist_converged_edges() -> int:
    """Persist converged rule prerequisites as canonical Dependency rows.

    Converged rules block the target while any convergence_target is unread.
    Each convergence target becomes a separate Dependency edge.

    Returns:
        Number of Dependency rows inserted.
    """
    db = await _get_db_session()
    try:
        # Find all converged rules
        result = await db.execute(
            select(ContinuityRule)
            .where(ContinuityRule.satisfaction_type == "converged")
        )
        rules = result.scalars().all()

        logger.info(f"Found {len(rules)} converged ContinuityRules")

        inserted = 0
        for rule in rules:
            # Each converged rule has convergence_targets JSON
            # Example: [{"type": "issue", "id": 52322}, {"type": "issue", "id": 52323}]
            targets = rule.convergence_targets or []
            for target_info in targets:
                target_id = int(target_info["id"])
                target_type = str(target_info["type"])

                if target_type != "issue":
                    # Only issue targets become Dependency edges;
                    # crossover targets are handled separately
                    continue

                # Check if a Dependency row already exists for this edge
                existing = await db.execute(
                    select(Dependency).where(
                        Dependency.source_issue_id == rule.source_id,
                        Dependency.target_issue_id == target_id,
                    )
                )
                if existing.scalar_one_or_none() is not None:
                    # Dependency row already exists; skip
                    continue

                # Insert new Dependency row with note = NULL (canonical set)
                new_dep = Dependency(
                    source_issue_id=rule.source_id,
                    target_issue_id=target_id,
                    # note stays NULL by default
                )
                db.add(new_dep)
                inserted += 1

        if inserted > 0:
            await db.commit()
        logger.info(f"Inserted {inserted} converged Dependency rows")
        return inserted
    finally:
        await db.close()


async def main() -> None:
    """Run the persistence script."""
    item_read_inserted = await persist_rule_native_item_read_edges()
    converged_inserted = await persist_converged_edges()
    total = item_read_inserted + converged_inserted
    logger.info(f"Total canonical Dependency rows persisted: {total}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    asyncio.run(main())