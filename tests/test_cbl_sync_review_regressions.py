"""Regression coverage for CBL synchronization review findings."""

from httpx import AsyncClient
import pytest


def _payload(*, repository: str, revision: str) -> dict:
    """Build one valid single-list synchronization payload.

    Args:
        repository: Source repository identity.
        revision: Source revision SHA.

    Returns:
        Valid API payload containing one X-Men issue.
    """
    return {
        "repository": repository,
        "revision_sha": revision,
        "lists": [
            {
                "source_path": "Marvel/X-Men/test.cbl",
                "content_hash": "b" * 64,
                "name": "Test X-Men Order",
                "declared_issue_count": 1,
                "books": [
                    {
                        "position": 1,
                        "series": "Uncanny X-Men",
                        "issue_number": "360",
                        "volume_year": 1981,
                        "publication_year": 1998,
                        "comicvine_series_id": None,
                        "comicvine_issue_id": None,
                    }
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_cbl_source_status_rejects_blank_repository(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitespace-only source identities return 422 instead of 500."""
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    response = await auth_client.get(
        "/api/v1/cbl-sync/source",
        params={"repository": "   "},
        headers={"X-Release-Writer-Token": "writer-secret"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_existing_cbl_source_enters_pending_for_next_revision(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later revision becomes pending even when list content is unchanged."""
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    headers = {"X-Release-Writer-Token": "writer-secret"}
    repository = "tests/cbl-next-revision"
    first_revision = "1" * 40
    second_revision = "2" * 40

    first = await auth_client.post(
        "/api/v1/cbl-sync/batch",
        json=_payload(repository=repository, revision=first_revision),
        headers=headers,
    )
    assert first.status_code == 200
    finalized = await auth_client.post(
        "/api/v1/cbl-sync/finalize",
        json={
            "repository": repository,
            "revision_sha": first_revision,
            "active_paths": ["Marvel/X-Men/test.cbl"],
            "protected_paths": [],
        },
        headers=headers,
    )
    assert finalized.status_code == 200

    second = await auth_client.post(
        "/api/v1/cbl-sync/batch",
        json=_payload(repository=repository, revision=second_revision),
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["unchanged_lists"] == 1

    source = await auth_client.get(
        "/api/v1/cbl-sync/source",
        params={"repository": repository},
        headers=headers,
    )
    assert source.status_code == 200
    assert source.json()["revision_sha"] == f"pending:{second_revision}"


@pytest.mark.asyncio
async def test_cbl_finalize_rejects_revision_without_matching_batch(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finalization cannot publish a revision that never entered pending state."""
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    headers = {"X-Release-Writer-Token": "writer-secret"}
    repository = "tests/cbl-finalize-mismatch"
    imported_revision = "3" * 40
    unimported_revision = "4" * 40

    batch = await auth_client.post(
        "/api/v1/cbl-sync/batch",
        json=_payload(repository=repository, revision=imported_revision),
        headers=headers,
    )
    assert batch.status_code == 200

    response = await auth_client.post(
        "/api/v1/cbl-sync/finalize",
        json={
            "repository": repository,
            "revision_sha": unimported_revision,
            "active_paths": ["Marvel/X-Men/test.cbl"],
            "protected_paths": [],
        },
        headers=headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_cbl_sync_rejects_revision_that_cannot_fit_pending_marker(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revision validation reserves room for the pending prefix in persistence."""
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    response = await auth_client.post(
        "/api/v1/cbl-sync/batch",
        json=_payload(
            repository="tests/cbl-validation-limits",
            revision="5" * 57,
        ),
        headers={"X-Release-Writer-Token": "writer-secret"},
    )
    assert response.status_code == 422
