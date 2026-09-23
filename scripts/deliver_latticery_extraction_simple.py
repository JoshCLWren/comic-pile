"""Dry-run helper for the first Latticery extraction slice delivery.

Validates staging files, adapts them to the Latticery package layout, and
prints the delivery plan without mutating any repository. The executable
path is ``scripts/deliver_latticery_extraction.py``.

Usage:
    python scripts/deliver_latticery_extraction_simple.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _ensure_project_on_path() -> None:
    """Prepend the repository root to ``sys.path`` for app imports."""
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def simulate_delivery() -> None:
    """Validate extraction files and print the delivery plan (no mutations)."""
    _ensure_project_on_path()
    from scripts.deliver_latticery_extraction import (
        FILE_MAP,
        build_delivery_request,
        build_file_payloads,
    )
    from app.services.delivery import DeliveryService

    print("Latticery extraction slice delivery dry run")
    print("=" * 60)

    files = build_file_payloads()
    print(f"Prepared {len(files)} file payload(s):")
    for payload in files:
        print(f"  - {payload.path} ({len(payload.content)} bytes)")

    request = build_delivery_request(files)
    print("\nDelivery request:")
    print(f"  Target: {request.target_repository}")
    print(f"  Branch: {request.branch_name}")
    print(f"  Base: {request.base_branch}")
    print(f"  Issue: #{request.issue_number}")
    print(f"  Worker: {request.worker_id}")
    print(f"  Mapped paths: {len(FILE_MAP)}")

    service = DeliveryService()
    print("\nDelivery service:")
    print(f"  Allowed targets: {sorted(service.ALLOWED_TARGET_REPOS)}")
    credential = service.resolve_credential_source(request.target_repository)
    print(f"  Required credential: {credential}")

    print("\nNext steps for actual delivery:")
    print("  1. Set DATABASE_URL and LATTICERY_TOKEN (repo scope for Latticery)")
    print("  2. Run: python scripts/deliver_latticery_extraction.py")
    print("  3. Verify the Latticery PR contains the three delivered files")
    print("  4. Link the Latticery PR from ComicPile issue #2875")

    print("\nIssue #2875 status after a successful delivery run:")
    print("  - Latticery branch with extraction content")
    print("  - Latticery PR opened and linked from the coordinating issue")
    print("  - Latticery tests run on the target repository CI")
    print("This dry run does not satisfy those acceptance criteria by itself.")


def main() -> None:
    """Main entry point."""
    try:
        simulate_delivery()
    except Exception as e:
        print(f"Dry run failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
