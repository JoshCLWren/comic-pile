"""Factory script to deliver extracted Latticery modules.

Reads the ComicPile staging files under ``latticery_extraction/``, rewrites
package imports for the ``latticery`` layout, and delivers them through the
cross-repository delivery service so the Latticery branch contains real file
content (not an empty branch).

Usage:
    python scripts/deliver_latticery_extraction.py

Requires ``DATABASE_URL`` and repository credentials (``LATTICERY_TOKEN`` for
JoshCLWren/Latticery). Fails closed when credentials are unavailable.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Staging file → Latticery repository path.
FILE_MAP: tuple[tuple[str, str], ...] = (
    ("dependency_policy.py", "src/latticery/dependency_policy.py"),
    ("executable_policy.py", "src/latticery/executable_policy.py"),
    ("test_dependency_executable_policy.py", "tests/test_dependency_executable_policy.py"),
)


def _ensure_project_on_path() -> None:
    """Prepend the repository root to ``sys.path`` for app imports."""
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def to_latticery_source(source: str) -> str:
    """Rewrite ComicPile staging imports to the Latticery package layout.

    Args:
        source: Raw staging file text.

    Returns:
        Source text using ``latticery.*`` imports.
    """
    return source.replace("latticery_extraction.", "latticery.")


def build_file_payloads() -> list:
    """Load and adapt extraction files for delivery.

    Returns:
        List of DeliveryFilePayload entries for the delivery request.

    Raises:
        RuntimeError: If a staging file is missing.
    """
    _ensure_project_on_path()
    from app.schemas.delivery import DeliveryFilePayload

    extraction_dir = PROJECT_ROOT / "latticery_extraction"
    if not extraction_dir.exists():
        raise RuntimeError(f"Extraction directory not found: {extraction_dir}")

    payloads = []
    missing: list[str] = []
    for source_name, target_path in FILE_MAP:
        source_path = extraction_dir / source_name
        if not source_path.exists():
            missing.append(str(source_path))
            continue
        raw = source_path.read_text(encoding="utf-8")
        payloads.append(
            DeliveryFilePayload(path=target_path, content=to_latticery_source(raw))
        )
    if missing:
        raise RuntimeError(f"Missing extraction files: {missing}")
    return payloads


def build_delivery_request(files: list):
    """Build the CrossRepoDeliveryRequest for the first extraction slice.

    Args:
        files: Adapted file payloads to deliver.

    Returns:
        CrossRepoDeliveryRequest targeting JoshCLWren/Latticery.
    """
    _ensure_project_on_path()
    from app.schemas.delivery import CrossRepoDeliveryRequest

    return CrossRepoDeliveryRequest(
        target_repository="JoshCLWren/Latticery",
        branch_name="factory/2875-first-extraction-slice",
        base_branch="main",
        title="Add first Latticery extraction slice: dependency and executable policy",
        body=(
            "Delivers the first pure dependency/executable-work policy slice "
            "from ComicPile staging (`latticery_extraction/`) into Latticery.\n\n"
            "Modules:\n"
            "- `src/latticery/dependency_policy.py`\n"
            "- `src/latticery/executable_policy.py`\n"
            "- `tests/test_dependency_executable_policy.py`\n\n"
            "Coordination issue: JoshCLWren/comic-pile#2875\n"
            "Cross-repo bridge: JoshCLWren/comic-pile#2874\n"
            "Prior extraction staging: JoshCLWren/comic-pile#2870\n\n"
            "Do not auto-merge until Latticery CI/review gates pass."
        ),
        issue_number=2875,
        worker_id="factory-54",
        commit_message="Add first Latticery extraction slice (issue 2875)",
        files=files,
    )


async def deliver_extraction_to_latticery() -> None:
    """Deliver extracted policy modules to the Latticery repository."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required")

    _ensure_project_on_path()
    from app.database import AsyncSessionLocal, async_engine
    from app.services.delivery import DeliveryService

    files = build_file_payloads()
    delivery_request = build_delivery_request(files)

    delivery_service = DeliveryService()
    print(f"Starting delivery to {delivery_request.target_repository}")
    print(f"Branch: {delivery_request.branch_name}")
    print(f"Base: {delivery_request.base_branch}")
    print(f"Files: {len(delivery_request.files)}")

    try:
        async with AsyncSessionLocal() as db:
            result = await delivery_service.deliver_to_target(db, delivery_request)
    finally:
        await async_engine.dispose()

    if not result.success:
        raise RuntimeError(f"Delivery failed: {result.error_message}")

    print("Delivery successful!")
    print(f"  Target: {result.target_repository}")
    print(f"  Branch: {result.target_branch}")
    print(f"  PR: #{result.target_pr_number}")
    print(f"  Credential: {result.credential_source}")
    if result.target_pr_number is not None:
        print(
            "  URL: "
            f"https://github.com/JoshCLWren/Latticery/pull/{result.target_pr_number}"
        )


async def main() -> None:
    """Main entry point."""
    try:
        await deliver_extraction_to_latticery()
        print("First Latticery extraction slice delivered.")
    except Exception as e:
        print(f"Delivery failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
