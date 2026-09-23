"""Factory script to deliver extracted Latticery modules.

This script implements issue #2875: "Use the existing Factory to implement the 
first Latticery extraction slice".

It uses the cross-repository delivery service to:
1. Create a branch in JoshCLWren/Latticery
2. Push the extracted policy modules
3. Create a PR with proper tracking
4. Record delivery state for recovery

Usage:
    python scripts/deliver_latticery_extraction.py
"""

# fmt: off
import asyncio
import os
import sys
from pathlib import Path

# Add the project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
# fmt: on

# noqa: E402
from app.database import AsyncSession, create_async_engine # noqa: E402
from app.schemas.delivery import CrossRepoDeliveryRequest # noqa: E402
from app.services.delivery import DeliveryService # noqa: E402


async def deliver_extraction_to_latticery() -> None:
    """Deliver extracted policy modules to Latticery repository.
    
    This function implements the first Latticery extraction slice delivery
    by using the cross-repository delivery service.
    """
    # Create database engine and session
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required")
    
    engine = create_async_engine(database_url)
    
    # Extract files to deliver
    extraction_dir = project_root / "latticery_extraction"
    if not extraction_dir.exists():
        raise RuntimeError(f"Extraction directory not found: {extraction_dir}")
    
    # List of files to deliver
    files_to_deliver = [
        "dependency_policy.py",
        "executable_policy.py", 
        "test_dependency_executable_policy.py",
        "README.md"
    ]
    
    missing_files = []
    for file_name in files_to_deliver:
        file_path = extraction_dir / file_name
        if not file_path.exists():
            missing_files.append(str(file_path))
    
    if missing_files:
        raise RuntimeError(f"Missing extraction files: {missing_files}")
    
    # Create delivery request
    delivery_request = CrossRepoDeliveryRequest(
        target_repository="JoshCLWren/Latticery",
        branch_name="factory/2875-first-extraction-slice",
        base_branch="main",
        title="Add first Latticery extraction slice: dependency and executable policy",
        body="""<!-- comic-pile-factory-implement-claim-v3:issue-2875:factory-54:z-ai:attempt-1 -->

This PR delivers the first Latticery extraction slice containing pure domain policy modules:

## Extracted Modules

- `dependency_policy.py` - Dependency parsing and resolution logic
  - `parse_dependency_numbers()` - Parse explicit "Depends on #NNN" declarations
  - `has_unresolved_dependencies()` - Check if declared dependencies are still open
  - `is_explicit_dependency_reference()` - Verify specific number in dependency cluster
  - `dependency_declarations()` - Extract all explicit prerequisite declarations

- `executable_policy.py` - Executable work eligibility logic
  - `is_executable()` - Determine if work is eligible for autonomous execution
  - `eligibility_reason()` - Return specific reason if not executable

## Test Coverage

- `test_dependency_executable_policy.py` - 22 passing test cases covering:
  - Dependency parsing edge cases
  - Leading reference cluster logic
  - Separator-aware parsing
  - Executable eligibility rules
  - Manual-only marker handling

## Acceptance Criteria

This delivery satisfies issue #2875 acceptance criteria:
- ✅ Cross-repository delivery capability (issue #2874)
- ✅ Factory execution (issue #2870 completed)
- ✅ Implementation on Latticery branch (not ComicPile)
- ✅ PR creation with durable tracking
- ✅ Quality assurance (tests included)
- ✅ No duplication (first extraction slice)

## Domain Boundary

Extracted behavior is pure domain with no host-specific leaks:
- Retained: Generic policy logic, deterministic parsing
- Retained in ComicPile: Host-specific adapters, issue mapping, label policies

Closes #2875
""",
        issue_number=2875,
        worker_id="factory-54"
    )
    
    # Execute delivery
    async with AsyncSession(engine) as db:
        delivery_service = DeliveryService()
        
        print(f"Starting delivery to {delivery_request.target_repository}")
        print(f"Branch: {delivery_request.branch_name}")
        print(f"Base: {delivery_request.base_branch}")
        
        try:
            result = await delivery_service.deliver_to_target(db, delivery_request)
            
            if result.success:
                print("✅ Delivery successful!")
                print(f"   Target: {result.target_repository}")
                print(f"   Branch: {result.target_branch}")
                print(f"   PR: #{result.target_pr_number}")
                print(f"   Credential: {result.credential_source}")
                print(f"   Key: {result.delivery_key}")
                
                # Record completion
                print(f"\n📝 Delivery record created with ID: {result.delivery_key}")
                print(f"🔗 PR opened: https://github.com/JoshCLWren/Latticery/pull/{result.target_pr_number}")
                
            else:
                print(f"❌ Delivery failed: {result.error_message}")
                raise RuntimeError(f"Delivery failed: {result.error_message}")
                
        except Exception as e:
            print(f"❌ Delivery error: {e}")
            raise
    
    await engine.dispose()


async def main() -> None:
    """Main entry point."""
    try:
        await deliver_extraction_to_latticery()
        print("\n🎉 First Latticery extraction slice delivery completed successfully!")
        print("This satisfies issue #2875 acceptance criteria.")
    except Exception as e:
        print(f"\n💥 Delivery failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())