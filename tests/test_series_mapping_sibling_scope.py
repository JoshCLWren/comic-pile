"""Sibling-scope contract tests for the series-mapping preview and commit surfaces.

Issue #3159 reported that the sibling-mapping offer promised by the sibling-scope
logic in :func:`app.services.catalog.build_series_mapping_plan` never surfaced.
The preview rows the offer depends on are proven here: a confirmed origin issue
licenses sibling scope, exact sibling numbers become bulk-safe rows, and the
commit surface confirms exactly those rows.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread

PREVIEW_URL = "/api/v1/catalog/series-mappings/preview"
COMMIT_URL = "/api/v1/catalog/series-mappings/commit"

VOLUME_ID = 20764
ORIGIN_COMICVINE_ISSUE_ID = 400012345
SIBLING_COMICVINE_ISSUE_IDS = {2: 400012346, 3: 400012347}


def _volume_payload() -> dict[str, object]:
    """Return a ComicVine volume payload for the shared test volume."""
    return {
        "id": VOLUME_ID,
        "name": "Saga (2012)",
        "publisher": {"name": "Image Comics"},
        "start_year": 2012,
        "count_of_issues": 60,
        "site_detail_url": f"https://comicvine.gamespot.com/saga/4050-{VOLUME_ID}/",
        "image": {"medium_url": "http://example.com/volume.jpg"},
    }


def _roster_row(comicvine_issue_id: int, issue_number: str) -> dict[str, object]:
    """Return one ComicVine roster row for the shared test volume."""
    return {
        "id": comicvine_issue_id,
        "issue_number": issue_number,
        "name": f"Saga #{issue_number}",
        "cover_date": "2012-01-01",
        "store_date": None,
        "image": {"small_url": f"http://example.com/{comicvine_issue_id}.jpg"},
        "site_detail_url": (
            f"https://comicvine.gamespot.com/saga-{issue_number}/4000-{comicvine_issue_id}/"
        ),
        "volume": {"id": VOLUME_ID},
    }


def _patch_comicvine(roster: list[dict[str, object]]):
    """Patch the shared catalog's ComicVine client to serve ``roster``.

    Args:
        roster: Provider volume issues the fake client should return.

    Returns:
        A patcher usable as a context manager.
    """
    mock_client = AsyncMock()
    mock_client.fetch_volume.return_value = AsyncMock(payload={"results": _volume_payload()})
    mock_client.fetch_volume_issues.return_value = roster
    return patch("app.services.catalog._get_comicvine_client", return_value=mock_client)


async def _confirm_origin_issue(db: AsyncSession, issue: Issue) -> None:
    """Attach a confirmed ComicVine issue identity to the anchor issue.

    Args:
        db: Database session.
        issue: Anchor ComicPile issue to confirm.
    """
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=str(ORIGIN_COMICVINE_ISSUE_ID),
        external_url=f"https://comicvine.gamespot.com/issue/4000-{ORIGIN_COMICVINE_ISSUE_ID}/",
        metadata_json={"name": "Saga #1", "issue_number": "1"},
    )
    db.add(identity)
    await db.flush()
    db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="confirmed",
            evidence_source="user_confirmed",
            confidence=1.0,
        )
    )
    await db.commit()


async def _create_thread_with_issues(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    issue_numbers: list[str],
) -> tuple[Thread, list[Issue]]:
    """Create one thread with the requested numbered issues.

    Args:
        db: Database session.
        user_id: Owner user ID.
        title: Thread title.
        issue_numbers: Issue numbers in reading order.

    Returns:
        The created thread and its issues, ordered by position.
    """
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=len(issue_numbers),
        queue_position=90,
        status="active",
        user_id=user_id,
    )
    db.add(thread)
    await db.flush()

    issues = [
        Issue(
            thread_id=thread.id,
            issue_number=number,
            position=position,
            status="unread",
        )
        for position, number in enumerate(issue_numbers, start=1)
    ]
    for issue in issues:
        db.add(issue)
    await db.flush()
    await db.commit()

    for issue in issues:
        await db.refresh(issue)
    return thread, issues


def _row_for(rows: list[dict[str, object]], issue_id: int) -> dict[str, object]:
    """Return the preview row that reports a locally owned issue.

    Args:
        rows: Preview rows.
        issue_id: ComicPile issue ID to find.

    Returns:
        The matching row.

    Raises:
        AssertionError: When no row reports the issue.
    """
    matching = [row for row in rows if row.get("issue_id") == issue_id and row.get("thread_id")]
    assert len(matching) == 1, f"expected exactly one owned row for issue {issue_id}"
    return matching[0]


def _approvable_row_ids(rows: list[dict[str, object]]) -> list[str]:
    """Return the row ids a caller may bulk-approve.

    Args:
        rows: Preview rows.

    Returns:
        Bulk-safe row ids that belong to a locally owned issue.
    """
    return sorted(
        str(row["row_id"])
        for row in rows
        if row.get("classification") == "safe_exact_match" and row.get("thread_id")
    )


class TestSiblingScopePreview:
    """The preview surface must license sibling scope and expose safe sibling rows."""

    @pytest.mark.asyncio
    async def test_confirmed_origin_offers_exact_sibling_matches(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """A corrected issue offers its unmapped siblings whose numbers match exactly."""
        origin = sample_data["issue"]
        await _confirm_origin_issue(async_db, origin)

        roster = [
            _roster_row(ORIGIN_COMICVINE_ISSUE_ID, "1"),
            _roster_row(SIBLING_COMICVINE_ISSUE_IDS[2], "2"),
            _roster_row(SIBLING_COMICVINE_ISSUE_IDS[3], "3"),
        ]

        with _patch_comicvine(roster):
            response = await auth_client.post(
                PREVIEW_URL,
                json={
                    "origin_issue_id": origin.id,
                    "provider": "comicvine",
                    "provider_series_external_id": str(VOLUME_ID),
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["scope"]["status"] == "available"
        assert data["preview_token"] is not None
        assert data["provider_series"]["name"] == "Saga (2012)"

        sibling_two = _row_for(data["rows"], 2)
        sibling_three = _row_for(data["rows"], 3)
        assert sibling_two["classification"] == "safe_exact_match"
        assert sibling_two["default_selected"] is True
        assert sibling_two["proposed_mapping"] is True
        assert sibling_two["row_id"] == "issue:2"
        assert sibling_two["thread_id"] == origin.thread_id
        assert sibling_three["classification"] == "safe_exact_match"
        assert sibling_three["default_selected"] is True
        assert sibling_three["row_id"] == "issue:3"

        # The corrected anchor is settled evidence and is never proposed for a rewrite.
        anchor = _row_for(data["rows"], origin.id)
        assert anchor["classification"] == "already_confirmed"
        assert anchor["default_selected"] is False

        # Siblings the volume does not carry stay unresolved instead of being offered.
        unmatched = _row_for(data["rows"], 4)
        assert unmatched["classification"] == "unresolved"
        assert unmatched["default_selected"] is False

        # Counts must describe exactly the rows the preview reports.
        assert sum(data["counts"].values()) == len(data["rows"])

    @pytest.mark.asyncio
    async def test_ambiguous_sibling_numbers_stay_out_of_the_safe_offer(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """A sibling whose number is ambiguous in the volume is never bulk-safe."""
        origin = sample_data["issue"]
        await _confirm_origin_issue(async_db, origin)

        roster = [
            _roster_row(ORIGIN_COMICVINE_ISSUE_ID, "1"),
            _roster_row(SIBLING_COMICVINE_ISSUE_IDS[2], "2"),
            _roster_row(SIBLING_COMICVINE_ISSUE_IDS[2] + 1, "2"),
            _roster_row(SIBLING_COMICVINE_ISSUE_IDS[3], "3"),
        ]

        with _patch_comicvine(roster):
            response = await auth_client.post(
                PREVIEW_URL,
                json={
                    "origin_issue_id": origin.id,
                    "provider": "comicvine",
                    "provider_series_external_id": str(VOLUME_ID),
                },
            )

        assert response.status_code == 200
        data = response.json()

        ambiguous = _row_for(data["rows"], 2)
        assert ambiguous["classification"] == "needs_review_ambiguous"
        assert ambiguous["default_selected"] is False
        assert "issue:2" not in _approvable_row_ids(data["rows"])

        # The unambiguous sibling is still offered, so one bad number cannot block the rest.
        assert "issue:3" in _approvable_row_ids(data["rows"])

    @pytest.mark.asyncio
    async def test_sibling_scope_requires_confirmed_origin_evidence(
        self, auth_client: AsyncClient, sample_data
    ) -> None:
        """Thread membership alone must not license sibling scope."""
        origin = sample_data["issue"]

        roster = [
            _roster_row(ORIGIN_COMICVINE_ISSUE_ID, "1"),
            _roster_row(SIBLING_COMICVINE_ISSUE_IDS[2], "2"),
        ]

        with _patch_comicvine(roster):
            response = await auth_client.post(
                PREVIEW_URL,
                json={
                    "origin_issue_id": origin.id,
                    "provider": "comicvine",
                    "provider_series_external_id": str(VOLUME_ID),
                },
            )

        assert response.status_code == 200
        data = response.json()
        owned_issue_ids = {
            row["issue_id"] for row in data["rows"] if row.get("thread_id") is not None
        }
        assert owned_issue_ids == set()

    @pytest.mark.asyncio
    async def test_special_sibling_numbers_are_excluded_from_the_offer(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """A sibling named ``Annual`` is excluded rather than offered."""
        user = sample_data["user"]
        _, issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="Sibling Specials",
            issue_numbers=["1", "2", "Annual"],
        )
        origin = issues[0]
        await _confirm_origin_issue(async_db, origin)

        roster = [
            _roster_row(ORIGIN_COMICVINE_ISSUE_ID, "1"),
            _roster_row(SIBLING_COMICVINE_ISSUE_IDS[2], "2"),
            _roster_row(SIBLING_COMICVINE_ISSUE_IDS[3], "Annual"),
        ]

        with _patch_comicvine(roster):
            response = await auth_client.post(
                PREVIEW_URL,
                json={
                    "origin_issue_id": origin.id,
                    "provider": "comicvine",
                    "provider_series_external_id": str(VOLUME_ID),
                },
            )

        assert response.status_code == 200
        data = response.json()

        annual = _row_for(data["rows"], issues[2].id)
        assert annual["classification"] == "excluded_special"
        assert annual["default_selected"] is False
        assert f"issue:{issues[2].id}" not in _approvable_row_ids(data["rows"])

        assert f"issue:{issues[1].id}" in _approvable_row_ids(data["rows"])


class TestSiblingScopeCommit:
    """The commit surface must confirm exactly the approved sibling rows."""

    @pytest.mark.asyncio
    async def test_commit_confirms_approved_sibling_rows(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """Approving the preview's safe rows confirms every selected sibling identity."""
        origin = sample_data["issue"]
        await _confirm_origin_issue(async_db, origin)

        roster = [
            _roster_row(ORIGIN_COMICVINE_ISSUE_ID, "1"),
            _roster_row(SIBLING_COMICVINE_ISSUE_IDS[2], "2"),
            _roster_row(SIBLING_COMICVINE_ISSUE_IDS[3], "3"),
        ]

        with _patch_comicvine(roster):
            preview = await auth_client.post(
                PREVIEW_URL,
                json={
                    "origin_issue_id": origin.id,
                    "provider": "comicvine",
                    "provider_series_external_id": str(VOLUME_ID),
                },
            )
        assert preview.status_code == 200
        preview_data = preview.json()
        preview_token = preview_data["preview_token"]
        assert preview_token is not None
        approved_row_ids = _approvable_row_ids(preview_data["rows"])
        assert approved_row_ids == ["issue:2", "issue:3"]

        with (
            _patch_comicvine(roster),
            patch(
                "app.services.comicvine_fallback.refresh_issue_metadata",
                new=AsyncMock(),
            ),
        ):
            commit = await auth_client.post(
                COMMIT_URL,
                json={
                    "preview_token": preview_token,
                    "idempotency_key": "issue-3159-siblings",
                    "approved_row_ids": approved_row_ids,
                },
            )

        assert commit.status_code == 200
        commit_data = commit.json()
        assert sorted(commit_data["confirmed_issue_ids"]) == [2, 3]
        assert commit_data["series_mapping"]["external_id"] == str(VOLUME_ID)
        assert commit_data["series_mapping"]["status"] == "confirmed"

        mapping_rows = (
            await async_db.execute(
                select(IssueExternalIdentityMapping, ExternalIdentity)
                .join(
                    ExternalIdentity,
                    ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
                )
                .where(
                    IssueExternalIdentityMapping.issue_id.in_([2, 3]),
                    IssueExternalIdentityMapping.status == "confirmed",
                )
            )
        ).all()
        confirmed_external_ids = {identity.external_id for _, identity in mapping_rows}
        assert confirmed_external_ids == {
            str(SIBLING_COMICVINE_ISSUE_IDS[2]),
            str(SIBLING_COMICVINE_ISSUE_IDS[3]),
        }

        thread_series_rows = (
            await async_db.execute(
                select(ThreadExternalSeriesMapping).where(
                    ThreadExternalSeriesMapping.thread_id == origin.thread_id,
                    ThreadExternalSeriesMapping.status == "confirmed",
                )
            )
        ).scalars().all()
        assert len(thread_series_rows) == 1

    @pytest.mark.asyncio
    async def test_commit_is_idempotent_for_a_repeated_request(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """Retrying the same commit key replays the stored result instead of rewriting."""
        origin = sample_data["issue"]
        await _confirm_origin_issue(async_db, origin)

        roster = [
            _roster_row(ORIGIN_COMICVINE_ISSUE_ID, "1"),
            _roster_row(SIBLING_COMICVINE_ISSUE_IDS[2], "2"),
        ]

        with _patch_comicvine(roster):
            preview = await auth_client.post(
                PREVIEW_URL,
                json={
                    "origin_issue_id": origin.id,
                    "provider": "comicvine",
                    "provider_series_external_id": str(VOLUME_ID),
                },
            )
        assert preview.status_code == 200
        preview_data = preview.json()
        approved_row_ids = _approvable_row_ids(preview_data["rows"])
        payload = {
            "preview_token": preview_data["preview_token"],
            "idempotency_key": "issue-3159-retry",
            "approved_row_ids": approved_row_ids,
        }

        with (
            _patch_comicvine(roster),
            patch(
                "app.services.comicvine_fallback.refresh_issue_metadata",
                new=AsyncMock(),
            ),
        ):
            first = await auth_client.post(COMMIT_URL, json=payload)
            second = await auth_client.post(COMMIT_URL, json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["confirmed_issue_ids"] == second.json()["confirmed_issue_ids"]

    @pytest.mark.asyncio
    async def test_commit_refuses_provider_roster_rows(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """Provider inventory rows carry no local issue, so they are never committable."""
        origin = sample_data["issue"]
        await _confirm_origin_issue(async_db, origin)

        roster = [_roster_row(ORIGIN_COMICVINE_ISSUE_ID, "1")]
        with _patch_comicvine(roster):
            preview = await auth_client.post(
                PREVIEW_URL,
                json={
                    "origin_issue_id": origin.id,
                    "provider": "comicvine",
                    "provider_series_external_id": str(VOLUME_ID),
                },
            )
        assert preview.status_code == 200
        preview_data = preview.json()
        roster_row_ids = [
            str(row["row_id"])
            for row in preview_data["rows"]
            if row.get("thread_id") is None and row.get("classification") == "safe_exact_match"
        ]
        assert roster_row_ids, "expected the volume's exact-number roster row to be bulk-safe"

        with _patch_comicvine(roster):
            commit = await auth_client.post(
                COMMIT_URL,
                json={
                    "preview_token": preview_data["preview_token"],
                    "idempotency_key": "issue-3159-roster",
                    "approved_row_ids": roster_row_ids,
                },
            )

        assert commit.status_code == 422

    @pytest.mark.asyncio
    async def test_commit_refuses_rows_the_preview_did_not_mark_safe(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """An unresolved sibling row cannot be bulk-approved even when its id is valid."""
        origin = sample_data["issue"]
        await _confirm_origin_issue(async_db, origin)

        roster = [
            _roster_row(ORIGIN_COMICVINE_ISSUE_ID, "1"),
            _roster_row(SIBLING_COMICVINE_ISSUE_IDS[2], "2"),
        ]

        with _patch_comicvine(roster):
            preview = await auth_client.post(
                PREVIEW_URL,
                json={
                    "origin_issue_id": origin.id,
                    "provider": "comicvine",
                    "provider_series_external_id": str(VOLUME_ID),
                },
            )
        assert preview.status_code == 200
        preview_data = preview.json()
        unmatched = _row_for(preview_data["rows"], 4)
        assert unmatched["classification"] == "unresolved"

        with _patch_comicvine(roster):
            commit = await auth_client.post(
                COMMIT_URL,
                json={
                    "preview_token": preview_data["preview_token"],
                    "idempotency_key": "issue-3159-unsafe",
                    "approved_row_ids": [str(unmatched["row_id"])],
                },
            )

        assert commit.status_code == 422
        assert commit.json()["detail"] == "invalid_approved_row"