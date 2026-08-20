"""Additional release ledger edge-case coverage.

Supplements tests/test_release_api.py with public-read failure paths and
response-schema assertions not exercised elsewhere.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_public_release_get_unknown_id_returns_404(
    auth_client: AsyncClient,
) -> None:
    """Fetching a non-existent public release id returns not found.

    Args:
        auth_client: Authenticated async API client.
    """
    response = await auth_client.get("/api/v1/releases/999999")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_public_release_response_hides_source_provenance(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public GET must never leak source PR, merge SHA, or provenance metadata.

    Args:
        auth_client: Authenticated async API client.
        monkeypatch: Pytest environment patch helper.
    """
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    headers = {"X-Release-Writer-Token": "writer-secret"}
    now = datetime.now(UTC).isoformat()
    payload = {
        "source_repository": "JoshCLWren/comic-pile",
        "source_pr_number": 1400,
        "source_merge_sha": "d" * 40,
        "merged_at": now,
        "released_at": now,
        "category": "What's New",
        "title": "Release 1400",
        "summary": "A user-facing release summary for provenance test",
        "body": "Detailed release body",
        "visibility": "public",
        "status": "published",
        "sort_order": 0,
        "provenance_json": {"source": "github", "internal_note": "hidden"},
    }

    created = await auth_client.put("/api/v1/releases/", json=payload, headers=headers)
    assert created.status_code == 200
    release_id = created.json()["id"]

    fetched = await auth_client.get(f"/api/v1/releases/{release_id}")
    assert fetched.status_code == 200
    data = fetched.json()
    assert data["title"] == "Release 1400"
    assert data["id"] == release_id
    assert "source_pr_number" not in data
    assert "source_merge_sha" not in data
    assert "provenance_json" not in data
    assert "source_repository" not in data
    assert "internal_note" not in data
