from app.models.dependency import Dependency
from app.repositories import dependency_repository
from app.schemas.cbl_adoption import AdoptionPlan, AdoptionCommit
from app.services.api import api_client

async def audit_production_state(user_id: int, db: AsyncSession) -> dict:
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
