"""Release ledger API regression coverage."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
import pytest


@pytest.mark.asyncio
async def test_release_writer_requires_server_only_credential(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal authenticated users must not inherit release-writer authority.

    Args:
        auth_client: Authenticated async API client.
        monkeypatch: Pytest environment patch helper.

    Returns:
        None.
    """
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    payload = _release_payload(pr_number=1201, merge_sha="a" * 40)

    response = await auth_client.put("/api/v1/releases/", json=payload)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_release_upsert_is_idempotent_and_reconcilable(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retrying the same merged PR updates one durable release record.

    Args:
        auth_client: Authenticated async API client.
        monkeypatch: Pytest environment patch helper.

    Returns:
        None.
    """
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    headers = {"X-Release-Writer-Token": "writer-secret"}
    payload = _release_payload(pr_number=1202, merge_sha="b" * 40)

    first = await auth_client.put("/api/v1/releases/", json=payload, headers=headers)
    assert first.status_code == 200
    first_id = first.json()["id"]

    payload["summary"] = "Updated release summary"
    retry = await auth_client.put("/api/v1/releases/", json=payload, headers=headers)
    assert retry.status_code == 200
    assert retry.json()["id"] == first_id
    assert retry.json()["summary"] == "Updated release summary"

    reconcile = await auth_client.get(
        "/api/v1/releases/source",
        params={"source_repository": "JoshCLWren/comic-pile", "source_pr_number": 1202},
        headers=headers,
    )
    assert reconcile.status_code == 200
    assert reconcile.json()["exists"] is True
    assert reconcile.json()["release"]["id"] == first_id


@pytest.mark.asyncio
async def test_release_partial_retry_preserves_source_identity(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Omitting one identity on retry must not erase established provenance.

    Args:
        auth_client: Authenticated async API client.
        monkeypatch: Pytest environment patch helper.

    Returns:
        None.
    """
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    headers = {"X-Release-Writer-Token": "writer-secret"}
    payload = _release_payload(pr_number=1210, merge_sha="3" * 40)

    first = await auth_client.put("/api/v1/releases/", json=payload, headers=headers)
    assert first.status_code == 200

    retry_payload = dict(payload)
    retry_payload["source_merge_sha"] = None
    retry_payload["summary"] = "Retried with PR identity only"
    retry = await auth_client.put("/api/v1/releases/", json=retry_payload, headers=headers)

    assert retry.status_code == 200
    assert retry.json()["source_pr_number"] == 1210
    assert retry.json()["source_merge_sha"] == "3" * 40
    assert retry.json()["summary"] == "Retried with PR identity only"


@pytest.mark.asyncio
async def test_release_source_conflict_returns_409(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One merge SHA cannot silently move between distinct source PRs.

    Args:
        auth_client: Authenticated async API client.
        monkeypatch: Pytest environment patch helper.

    Returns:
        None.
    """
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    headers = {"X-Release-Writer-Token": "writer-secret"}
    shared_sha = "c" * 40

    first = await auth_client.put(
        "/api/v1/releases/",
        json=_release_payload(pr_number=1203, merge_sha=shared_sha),
        headers=headers,
    )
    assert first.status_code == 200

    conflict = await auth_client.put(
        "/api/v1/releases/",
        json=_release_payload(pr_number=1204, merge_sha=shared_sha),
        headers=headers,
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_public_release_list_filters_and_orders(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What's New sees only public published rows in deterministic newest-first order.

    Args:
        auth_client: Authenticated async API client.
        monkeypatch: Pytest environment patch helper.

    Returns:
        None.
    """
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    headers = {"X-Release-Writer-Token": "writer-secret"}
    now = datetime.now(UTC)

    older = _release_payload(pr_number=1205, merge_sha="d" * 40)
    older["released_at"] = (now - timedelta(days=1)).isoformat()
    newer_low = _release_payload(pr_number=1206, merge_sha="e" * 40)
    newer_low["released_at"] = now.isoformat()
    newer_low["sort_order"] = 1
    newer_high = _release_payload(pr_number=1207, merge_sha="f" * 40)
    newer_high["released_at"] = now.isoformat()
    newer_high["sort_order"] = 5
    internal = _release_payload(pr_number=1208, merge_sha="1" * 40)
    internal["visibility"] = "internal"
    draft = _release_payload(pr_number=1209, merge_sha="2" * 40)
    draft["status"] = "draft"

    for payload in (older, newer_low, newer_high, internal, draft):
        response = await auth_client.put("/api/v1/releases/", json=payload, headers=headers)
        assert response.status_code == 200

    response = await auth_client.get("/api/v1/releases/", params={"limit": 2, "offset": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [item["title"] for item in body["releases"]] == ["Release 1207", "Release 1206"]
    assert all("source_pr_number" not in item for item in body["releases"])
    assert all("source_merge_sha" not in item for item in body["releases"])
    assert all("provenance_json" not in item for item in body["releases"])

    second_page = await auth_client.get(
        "/api/v1/releases/",
        params={"limit": 2, "offset": 2},
    )
    assert second_page.status_code == 200
    assert [item["title"] for item in second_page.json()["releases"]] == ["Release 1205"]


def _release_payload(*, pr_number: int, merge_sha: str) -> dict[str, object]:
    """Build a valid merged-PR-backed release payload for API tests."""
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
async def test_public_release_payload_rejects_placeholder_content(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Placeholder-sized public copy must be rejected before it reaches What's New.

    Args:
        auth_client: Authenticated async API client.
        monkeypatch: Pytest environment patch helper.

    Returns:
        None.
    """
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    headers = {"X-Release-Writer-Token": "writer-secret"}
    payload = _release_payload(pr_number=1211, merge_sha="9" * 40)
    payload["title"] = "T"
    payload["summary"] = "S"

    response = await auth_client.put("/api/v1/releases/", json=payload, headers=headers)

    assert response.status_code == 422
    errors = response.json()["errors"]
    assert any(
        error["message"]
        == "Value error, title must contain meaningful release content "
        "(at least 4 visible characters)"
        for error in errors
    )


@pytest.mark.asyncio
async def test_release_retract_requires_writer_credential(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal authenticated users must not retract release records.

    Args:
        auth_client: Authenticated async API client.
        monkeypatch: Pytest environment patch helper.

    Returns:
        None.
    """
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")

    response = await auth_client.post("/api/v1/releases/1/retract")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_release_retract_removes_public_release(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retracted releases leave the public What's New list.

    Args:
        auth_client: Authenticated async API client.
        monkeypatch: Pytest environment patch helper.

    Returns:
        None.
    """
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    headers = {"X-Release-Writer-Token": "writer-secret"}
    payload = _release_payload(pr_number=1212, merge_sha="8" * 40)

    published = await auth_client.put("/api/v1/releases/", json=payload, headers=headers)
    assert published.status_code == 200
    release_id = published.json()["id"]

    listed = await auth_client.get("/api/v1/releases/", params={"limit": 100, "offset": 0})
    assert any(item["id"] == release_id for item in listed.json()["releases"])

    retracted = await auth_client.post(
        f"/api/v1/releases/{release_id}/retract",
        headers=headers,
    )
    assert retracted.status_code == 200
    assert retracted.json()["id"] == release_id
    assert retracted.json()["status"] == "retracted"

    after = await auth_client.get("/api/v1/releases/", params={"limit": 100, "offset": 0})
    assert all(item["id"] != release_id for item in after.json()["releases"])


@pytest.mark.asyncio
async def test_release_retract_missing_release_is_404(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retracting an unknown release id must return not found.

    Args:
        auth_client: Authenticated async API client.
        monkeypatch: Pytest environment patch helper.

    Returns:
        None.
    """
    monkeypatch.setenv("RELEASE_WRITER_TOKEN", "writer-secret")
    headers = {"X-Release-Writer-Token": "writer-secret"}

    response = await auth_client.post("/api/v1/releases/999999/retract", headers=headers)

    assert response.status_code == 404
