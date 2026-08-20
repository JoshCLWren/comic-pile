"""Release ledger API regression coverage for the database-backed release pipeline.

These tests exercise the public release pipeline end to end: writer-only
mutation is gated by the server-only credential, a published release is
durable and fetchable by id, and source provenance is hidden from public
readers. They mirror the contract enforced by ``app/api/releases.py``.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient


def _release_payload(*, pr_number: int, merge_sha: str) -> dict[str, object]:
    """Build a valid merged-PR-backed release payload for API tests.

    Args:
        pr_number: Source pull request number anchoring provenance.
        merge_sha: Source merge commit SHA anchoring provenance.

    Returns:
        A release upsert payload valid for the public release pipeline.
    """
    now = datetime.now(UTC).isoformat()
    return {
        "source_repository": "JoshCLWren/comic-pile",
        "source_pr_number": pr_number,
        "source_merge_sha": merge_sha,
        "merged_at": now,
        "released_at": now,
        "category": "What's New",
        "title": f"Release {pr_number}",
        "summary": "A user-facing release summary",
        "body": "More release detail",
        "visibility": "public",
        "status": "published",
        "sort_order": 0,
        "provenance_json": {"source": "github"},
    }


@pytest.mark.asyncio
async def test_release_writer_token_required_for_upsert(auth_client: AsyncClient) -> None:
    """Unauthenticated clients cannot publish releases.

    Args:
        auth_client: Authenticated async API client.
    """
    payload = _release_payload(pr_number=1301, merge_sha="a" * 40)

    response = await auth_client.put("/api/v1/releases/", json=payload)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_release_upsert_then_get_roundtrip(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A published release is durable, fetchable by id, and hides source provenance.

    Args:
        auth_client: Authenticated async API client.
        monkeypatch: Pytest environment patch helper.
    """
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    headers = {"X-Release-Writer-Token": "writer-secret"}
    payload = _release_payload(pr_number=1302, merge_sha="b" * 40)

    created = await auth_client.put("/api/v1/releases/", json=payload, headers=headers)
    assert created.status_code == 200
    release_id = created.json()["id"]

    fetched = await auth_client.get(f"/api/v1/releases/{release_id}")
    assert fetched.status_code == 200
    data = fetched.json()
    assert data["title"] == "Release 1302"
    assert "source_pr_number" not in data
    assert "source_merge_sha" not in data
    assert "provenance_json" not in data


@pytest.mark.asyncio
async def test_release_get_unknown_is_404(auth_client: AsyncClient) -> None:
    """Fetching an unknown public release id returns not found.

    Args:
        auth_client: Authenticated async API client.
    """
    response = await auth_client.get("/api/v1/releases/999999")

    assert response.status_code == 404
