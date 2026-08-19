"""Service-authorized CBL synchronization API regression coverage."""

from httpx import AsyncClient
import pytest


@pytest.mark.asyncio
async def test_cbl_sync_requires_server_only_credential(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal authenticated users must not inherit trusted automation authority."""
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")

    response = await auth_client.get(
        "/api/v1/cbl-sync/source",
        params={"repository": "example/cbl"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_cbl_batches_only_publish_revision_when_finalized(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial batch cannot make a mirror revision look fully synchronized."""
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    headers = {"X-Release-Writer-Token": "writer-secret"}
    repository = "tests/cbl-batch-finalize"
    revision = "a" * 40
    payload = {
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

    batch = await auth_client.post(
        "/api/v1/cbl-sync/batch",
        json=payload,
        headers=headers,
    )
    assert batch.status_code == 200
    assert batch.json()["inserted_lists"] == 1

    partial = await auth_client.get(
        "/api/v1/cbl-sync/source",
        params={"repository": repository},
        headers=headers,
    )
    assert partial.status_code == 200
    assert partial.json()["revision_sha"] == f"pending:{revision}"

    finalize = await auth_client.post(
        "/api/v1/cbl-sync/finalize",
        json={
            "repository": repository,
            "revision_sha": revision,
            "active_paths": ["Marvel/X-Men/test.cbl"],
            "protected_paths": [],
        },
        headers=headers,
    )
    assert finalize.status_code == 200

    complete = await auth_client.get(
        "/api/v1/cbl-sync/source",
        params={"repository": repository},
        headers=headers,
    )
    assert complete.status_code == 200
    assert complete.json()["revision_sha"] == revision


@pytest.mark.asyncio
async def test_cbl_batch_retry_is_content_idempotent(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retrying a previously persisted list does not rewrite its entries."""
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    headers = {"X-Release-Writer-Token": "writer-secret"}
    payload = {
        "repository": "tests/cbl-idempotent",
        "revision_sha": "c" * 40,
        "lists": [
            {
                "source_path": "Marvel/X-Men/retry.cbl",
                "content_hash": "d" * 64,
                "name": "Retry Order",
                "declared_issue_count": 1,
                "books": [
                    {
                        "position": 1,
                        "series": "X-Men",
                        "issue_number": "80",
                        "volume_year": 1991,
                        "publication_year": 1998,
                        "comicvine_series_id": None,
                        "comicvine_issue_id": None,
                    }
                ],
            }
        ],
    }

    first = await auth_client.post(
        "/api/v1/cbl-sync/batch", json=payload, headers=headers
    )
    retry = await auth_client.post(
        "/api/v1/cbl-sync/batch", json=payload, headers=headers
    )

    assert first.status_code == 200
    assert retry.status_code == 200
    assert retry.json()["unchanged_lists"] == 1
    assert retry.json()["entries_written"] == 0
