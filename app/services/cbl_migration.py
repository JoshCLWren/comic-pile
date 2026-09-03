"""CBL migration service for production cutover and legacy dependency cleanup.

This service handles the migration from legacy CBL dependency graphs to the
supported source-backed adoption/order model.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import dependency_repository
from app.schemas.cbl_adoption import AdoptionCommit
from app.services.api import api_client


async def audit_production_state(user_id: int, db: AsyncSession) -> dict:
    """Audit production state for CBL migration.

    Query dependencies for user with cbl-order:source:* notes and count
    active CBL source positions.

    Args:
        user_id: The user ID to audit.
        db: Database session.

    Returns:
        Dictionary with audit counts.
    """
    # Query dependencies for user with cbl-order:source:* notes
    cbl_dependencies = await dependency_repository.get_dependencies_by_user_and_note_prefix(
        db, user_id, "cbl-order:source:"
    )

    # Count active CBL source positions
    source_positions = set()
    for dep in cbl_dependencies:
        if dep.note.startswith("cbl-order:source:"):
            source = dep.note.split(":")[2]
            source_positions.add(source)

    return {
        "cbl_source_count": len(source_positions),
        "dependency_count": len(cbl_dependencies),
        # Add other required counts
    }


async def migrate_ultimate_universe(user_id: int, db: AsyncSession):
    """Migrate Ultimate Universe from legacy CBL to source-backed model.

    Performs the production cutover for Ultimate Universe source list #12.

    Args:
        user_id: The user ID to migrate.
        db: Database session.
    """
    # Step 1: Generate adoption plan for Ultimate Universe
    plan = await api_client.post("/api/cbl/adoption-plan", json={
        "user_id": user_id,
        "source_list_id": 12  # Ultimate Universe source list ID
    })

    # Step 2: Commit the adoption
    commit_data = AdoptionCommit(**plan.json())
    await api_client.post("/api/cbl/adopt", json=commit_data.dict())

    # Step 3: Verify Roll behavior
    # Implement verification logic here

    # Step 4: Remove legacy dependencies
    await dependency_repository.delete_dependencies_by_user_and_note_prefix(
        db, user_id, "cbl-order:source:12:"  # Scope to Ultimate Universe
    )

    # Refresh blocked state
    await api_client.post("/api/roll/refresh-blocked")


# Similar functions for other sources and cleanup
