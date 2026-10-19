"""Queue-thread bootstrap tests for the series-mapping preview and commit surfaces.

Issue #3727: the Queue ``Map series`` surface could not bootstrap a completely unmapped
thread. The generic preview only offers local issues once the anchor already carries
confirmed series evidence, so a wholly unmapped miniseries produced a provider-only plan
whose approval button read ``Map 0 issues``.

These tests pin the explicit ``queue_thread_bootstrap`` scope mode: it may propose the
anchor's entire owned thread (including its first issue), but only when every proposed issue
is a unique exact match against the selected volume's real roster on both sides. The generic
``confirmed_origin`` guard is proven intact alongside it.
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
from app.models.user import User

PREVIEW_URL = "/api/v1/catalog/series-mappings/preview"
COMMIT_URL = "/api/v1/catalog/series-mappings/commit"

VOLUME_ID = 20764
BOOTSTRAP_MODE = "queue_thread_bootstrap"


def _volume_payload() -> dict[str, object]:
    """Return a ComicVine volume payload for the shared test volume."""
    return {
        "id": VOLUME_ID,
        "name": "B.P.R.D.: King of Fear (2010)",
        "publisher": {"name": "Dark Horse Comics"},
        "start_year": 2010,
        "count_of_issues": 5,
        "site_detail_url": f"https://comicvine.gamespot.com/bprd-king-of-fear/4050-{VOLUME_ID}/",
        "image": {"medium_url": "http://example.com/volume.jpg"},
    }


def _roster_row(comicvine_issue_id: int, issue_number: str) -> dict[str, object]:
    """Return one ComicVine roster row for the shared test volume."""
    return {
        "id": comicvine_issue_id,
        "issue_number": issue_number,
        "name": f"B.P.R.D.: King of Fear #{issue_number}",
        "cover_date": "2010-01-01",
        "store_date": None,
        "image": {"small_url": f"http://example.com/{comicvine_issue_id}.jpg"},
        "site_detail_url": (
            f"https://comicvine.gamespot.com/bprd-{issue_number}/4000-{comicvine_issue_id}/"
        ),
        "volume": {"id": VOLUME_ID},
    }


def _patch_comicvine(roster: list[dict[str, object]]):
    """Patch the shared catalog's ComicVine client to serve ``roster``."""
    mock_client = AsyncMock()
    mock_client.fetch_volume.return_value = AsyncMock(payload={"results": _volume_payload()})
    mock_client.fetch_volume_issues.return_value = roster
    return patch("app.services.catalog._get_comicvine_client", return_value=mock_client)


async def _create_thread_with_issues(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    issue_numbers: list[str],
) -> tuple[Thread, list[Issue]]:
    """Create one thread with the requested numbered issues."""
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


async def _confirm_issue(
    db: AsyncSession,
    issue: Issue,
    *,
    external_id: str,
    provider: str = "comicvine",
) -> None:
    """Attach a confirmed issue identity for ``provider`` to ``issue``."""
    identity = ExternalIdentity(
        provider=provider,
        entity_type="issue",
        external_id=external_id,
        external_url=f"https://example.com/{provider}/4000-{external_id}",
        metadata_json={"name": f"Issue {issue.issue_number}", "issue_number": issue.issue_number,
                       "volume": {"id": VOLUME_ID, "name": "B.P.R.D.: King of Fear"},
                       "primary_image": "http://example.com/issue.jpg"},
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


def _bootstrap_payload(origin_issue_id: int, *, scope_mode: str | None = BOOTSTRAP_MODE) -> dict[str, object]:
    """Build a preview request body, optionally omitting the scope mode."""
    payload: dict[str, object] = {
        "origin_issue_id": origin_issue_id,
        "provider": "comicvine",
        "provider_series_external_id": str(VOLUME_ID),
    }
    if scope_mode is not None:
        payload["scope_mode"] = scope_mode
    return payload


def _owned_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Return the preview rows that report a locally owned issue."""
    return [row for row in rows if row.get("thread_id") is not None]


def _approvable_row_ids(rows: list[dict[str, object]]) -> list[str]:
    """Return the owned, bulk-safe row ids a caller may approve."""
    return sorted(
        str(row["row_id"])
        for row in rows
        if row.get("classification") == "safe_exact_match" and row.get("thread_id")
    )


class TestQueueThreadBootstrapPreview:
    """A completely unmapped owned thread must bootstrap against a matching volume."""

    @pytest.mark.asyncio
    async def test_unmapped_miniseries_preview_lists_all_five_owned_issues(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """The five-issue miniseries offers every issue, including the first, as safe."""
        user = sample_data["user"]
        thread, issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="B.P.R.D.: King of Fear",
            issue_numbers=["1", "2", "3", "4", "5"],
        )
        roster = [_roster_row(500000 + number, str(number)) for number in range(1, 6)]

        with _patch_comicvine(roster):
            response = await auth_client.post(PREVIEW_URL, json=_bootstrap_payload(issues[0].id))

        assert response.status_code == 200
        data = response.json()
        assert data["scope"]["status"] == "available"
        assert data["preview_token"] is not None
        assert data["provider_series"]["name"] == "B.P.R.D.: King of Fear (2010)"

        owned = _owned_rows(data["rows"])
        assert sorted(row["issue_id"] for row in owned) == sorted(issue.id for issue in issues)
        assert all(row["classification"] == "safe_exact_match" for row in owned)
        assert all(row["default_selected"] is True for row in owned)
        assert all(row["thread_id"] == thread.id for row in owned)

        # The first issue is eligible too: bootstrap is not a siblings-only offer.
        first = next(row for row in owned if row["issue_id"] == issues[0].id)
        assert first["classification"] == "safe_exact_match"

        # Every provider issue is claimed by an owned issue, so there is no leftover inventory.
        assert data["counts"]["safe_exact_match"] == 5
        assert data["counts"]["unresolved"] == 0
        assert sum(data["counts"].values()) == len(data["rows"])

    @pytest.mark.asyncio
    async def test_unmapped_miniseries_commit_confirms_all_five(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """Approving the five safe rows confirms all five identities and the thread series."""
        user = sample_data["user"]
        thread, issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="B.P.R.D.: King of Fear",
            issue_numbers=["1", "2", "3", "4", "5"],
        )
        roster = [_roster_row(500000 + number, str(number)) for number in range(1, 6)]

        with _patch_comicvine(roster):
            preview = await auth_client.post(PREVIEW_URL, json=_bootstrap_payload(issues[0].id))
        assert preview.status_code == 200
        preview_data = preview.json()
        approved = _approvable_row_ids(preview_data["rows"])
        assert approved == [f"issue:{issue.id}" for issue in issues]

        with (
            _patch_comicvine(roster),
            patch("app.services.comicvine_fallback.refresh_issue_metadata", new=AsyncMock()),
        ):
            commit = await auth_client.post(
                COMMIT_URL,
                json={
                    "preview_token": preview_data["preview_token"],
                    "idempotency_key": "issue-3727-bootstrap",
                    "approved_row_ids": approved,
                },
            )

        assert commit.status_code == 200
        commit_data = commit.json()
        assert sorted(commit_data["confirmed_issue_ids"]) == sorted(issue.id for issue in issues)
        assert commit_data["needs_review_issue_ids"] == []
        assert commit_data["series_mapping"]["external_id"] == str(VOLUME_ID)
        assert commit_data["series_mapping"]["status"] == "confirmed"

        confirmed = (
            await async_db.execute(
                select(IssueExternalIdentityMapping).where(
                    IssueExternalIdentityMapping.issue_id.in_([issue.id for issue in issues]),
                    IssueExternalIdentityMapping.status == "confirmed",
                )
            )
        ).scalars().all()
        assert len(confirmed) == 5

        thread_series = (
            await async_db.execute(
                select(ThreadExternalSeriesMapping).where(
                    ThreadExternalSeriesMapping.thread_id == thread.id,
                    ThreadExternalSeriesMapping.status == "confirmed",
                )
            )
        ).scalars().all()
        assert len(thread_series) == 1

    @pytest.mark.asyncio
    async def test_generic_mode_still_requires_confirmed_origin_evidence(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """The generic preview must not propose an unmapped thread just because it matches."""
        user = sample_data["user"]
        _, issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="Unconfirmed Origin",
            issue_numbers=["1", "2"],
        )
        roster = [_roster_row(500000 + number, str(number)) for number in (1, 2)]

        with _patch_comicvine(roster):
            response = await auth_client.post(
                PREVIEW_URL, json=_bootstrap_payload(issues[0].id, scope_mode=None)
            )

        assert response.status_code == 200
        data = response.json()
        assert _owned_rows(data["rows"]) == []

    @pytest.mark.asyncio
    async def test_bootstrap_scope_never_crosses_threads(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """Only the anchor's own thread is eligible; other owned threads stay provider-only."""
        user = sample_data["user"]
        anchor_thread, anchor_issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="Anchor Thread",
            issue_numbers=["1", "2"],
        )
        _, other_issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="Other Thread",
            issue_numbers=["3"],
        )
        roster = [_roster_row(500000 + number, str(number)) for number in (1, 2, 3, 4)]

        with _patch_comicvine(roster):
            response = await auth_client.post(
                PREVIEW_URL, json=_bootstrap_payload(anchor_issues[0].id)
            )

        assert response.status_code == 200
        data = response.json()
        owned = _owned_rows(data["rows"])
        assert {row["issue_id"] for row in owned} == {issue.id for issue in anchor_issues}
        assert all(row["thread_id"] == anchor_thread.id for row in owned)

        other_issue_ids = {issue.id for issue in other_issues}
        assert other_issue_ids.isdisjoint({row["issue_id"] for row in data["rows"]})

        # The other thread's number and the unmatched provider issue remain visible inventory.
        provider_only = [row for row in data["rows"] if row.get("thread_id") is None]
        assert len(provider_only) == 2
        assert data["counts"]["safe_exact_match"] == 2
        assert data["counts"]["unresolved"] == 2

    @pytest.mark.asyncio
    async def test_bootstrap_rejects_an_unowned_origin_issue(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """Another user's issue is not visible, so bootstrap cannot widen to it."""
        other_user = User(username="other-reader", created_at=sample_data["user"].created_at)
        async_db.add(other_user)
        await async_db.flush()
        _, other_issues = await _create_thread_with_issues(
            async_db,
            user_id=other_user.id,
            title="Someone Else's Thread",
            issue_numbers=["1"],
        )
        roster = [_roster_row(500001, "1")]

        with _patch_comicvine(roster):
            response = await auth_client.post(
                PREVIEW_URL, json=_bootstrap_payload(other_issues[0].id)
            )

        assert response.status_code == 200
        data = response.json()
        assert data["scope"]["status"] == "unavailable"
        assert data["scope"]["basis"] == "origin_issue_not_found"

    @pytest.mark.asyncio
    async def test_duplicate_numbers_on_the_roster_stay_ambiguous(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """A volume that holds several issues with one number never licenses a safe match."""
        user = sample_data["user"]
        _, issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="Duplicate Roster",
            issue_numbers=["1", "2"],
        )
        roster = [
            _roster_row(500001, "1"),
            _roster_row(500002, "2"),
            _roster_row(500003, "2"),
        ]

        with _patch_comicvine(roster):
            response = await auth_client.post(PREVIEW_URL, json=_bootstrap_payload(issues[0].id))

        assert response.status_code == 200
        data = response.json()
        rows_by_id = {row["issue_id"]: row for row in _owned_rows(data["rows"])}
        assert rows_by_id[issues[0].id]["classification"] == "safe_exact_match"
        assert rows_by_id[issues[1].id]["classification"] == "needs_review_ambiguous"
        assert f"issue:{issues[1].id}" not in _approvable_row_ids(data["rows"])

    @pytest.mark.asyncio
    async def test_duplicate_normalized_numbers_in_the_thread_stay_ambiguous(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """Distinct raw spellings that normalize alike are still ambiguous locally.

        The database enforces raw ``(thread_id, issue_number)`` uniqueness, so a local
        duplicate can only arise from two spellings that normalize to the same value. Both are
        ambiguous even when the volume holds exactly one issue of that number.
        """
        user = sample_data["user"]
        _, issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="Duplicate Local",
            issue_numbers=["1", "1.", "2"],
        )
        roster = [_roster_row(500001, "1"), _roster_row(500002, "2")]

        with _patch_comicvine(roster):
            response = await auth_client.post(PREVIEW_URL, json=_bootstrap_payload(issues[0].id))

        assert response.status_code == 200
        data = response.json()
        rows_by_id = {row["issue_id"]: row for row in _owned_rows(data["rows"])}
        assert rows_by_id[issues[0].id]["classification"] == "needs_review_ambiguous"
        assert rows_by_id[issues[1].id]["classification"] == "needs_review_ambiguous"
        assert rows_by_id[issues[2].id]["classification"] == "safe_exact_match"

    @pytest.mark.asyncio
    async def test_special_numbers_are_excluded_from_the_offer(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """A named ``Annual`` issue is excluded instead of offered for bulk confirmation."""
        user = sample_data["user"]
        _, issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="Bootstrap Specials",
            issue_numbers=["1", "2", "Annual"],
        )
        roster = [
            _roster_row(500001, "1"),
            _roster_row(500002, "2"),
            _roster_row(500003, "Annual"),
        ]

        with _patch_comicvine(roster):
            response = await auth_client.post(PREVIEW_URL, json=_bootstrap_payload(issues[0].id))

        assert response.status_code == 200
        data = response.json()
        rows_by_id = {row["issue_id"]: row for row in _owned_rows(data["rows"])}
        assert rows_by_id[issues[2].id]["classification"] == "excluded_special"
        assert rows_by_id[issues[0].id]["classification"] == "safe_exact_match"
        assert rows_by_id[issues[1].id]["classification"] == "safe_exact_match"

    @pytest.mark.asyncio
    async def test_mismatched_volume_produces_no_safe_plan(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """A volume whose numbers do not match the thread yields no safe scope."""
        user = sample_data["user"]
        _, issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="Mismatched Volume",
            issue_numbers=["1", "2", "3"],
        )
        roster = [_roster_row(500010, "10"), _roster_row(500011, "11")]

        with _patch_comicvine(roster):
            response = await auth_client.post(PREVIEW_URL, json=_bootstrap_payload(issues[0].id))

        assert response.status_code == 200
        data = response.json()
        assert data["scope"]["status"] == "unavailable"
        assert data["preview_token"] is None
        assert data["rows"] == []
        assert all(count == 0 for count in data["counts"].values())

    @pytest.mark.asyncio
    async def test_confirmed_disagreement_is_reported_as_a_conflict(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """A confirmed identity that disagrees with the selected volume is never rewritten."""
        user = sample_data["user"]
        _, issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="Confirmed Conflict",
            issue_numbers=["1", "2"],
        )
        await _confirm_issue(async_db, issues[0], external_id="999999")
        roster = [_roster_row(500001, "1"), _roster_row(500002, "2")]

        with _patch_comicvine(roster):
            response = await auth_client.post(PREVIEW_URL, json=_bootstrap_payload(issues[0].id))

        assert response.status_code == 200
        data = response.json()
        rows_by_id = {row["issue_id"]: row for row in _owned_rows(data["rows"])}
        assert rows_by_id[issues[0].id]["classification"] == "needs_review_conflict"
        assert rows_by_id[issues[0].id]["default_selected"] is False
        assert rows_by_id[issues[1].id]["classification"] == "safe_exact_match"
        assert f"issue:{issues[0].id}" not in _approvable_row_ids(data["rows"])

    @pytest.mark.asyncio
    async def test_confirmed_agreement_is_idempotent(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """A confirmed identity that agrees with the volume is settled, not re-proposed."""
        user = sample_data["user"]
        _, issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="Confirmed Agreement",
            issue_numbers=["1", "2"],
        )
        await _confirm_issue(async_db, issues[0], external_id="500001")
        roster = [_roster_row(500001, "1"), _roster_row(500002, "2")]

        with _patch_comicvine(roster):
            response = await auth_client.post(PREVIEW_URL, json=_bootstrap_payload(issues[0].id))

        assert response.status_code == 200
        data = response.json()
        rows_by_id = {row["issue_id"]: row for row in _owned_rows(data["rows"])}
        assert rows_by_id[issues[0].id]["classification"] == "already_confirmed"
        assert rows_by_id[issues[0].id]["default_selected"] is False
        assert rows_by_id[issues[1].id]["classification"] == "safe_exact_match"

    @pytest.mark.asyncio
    async def test_confirmed_identity_is_not_reported_as_missing_library_inventory(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """The provider issue a confirmed identity claims is never provider inventory.

        Re-opening the dialog after a partial confirmation must not claim that the volume
        holds an issue "not in your library" when that exact provider issue is already the
        confirmed identity of an owned issue in the thread.
        """
        user = sample_data["user"]
        _, issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="Confirmed Inventory",
            issue_numbers=["1", "2"],
        )
        await _confirm_issue(async_db, issues[0], external_id="500001")
        roster = [_roster_row(500001, "1"), _roster_row(500002, "2"), _roster_row(500003, "3")]

        with _patch_comicvine(roster):
            response = await auth_client.post(PREVIEW_URL, json=_bootstrap_payload(issues[0].id))

        assert response.status_code == 200
        data = response.json()

        # The confirmed identity's own provider issue is matched, not missing inventory.
        provider_only = [row for row in data["rows"] if row.get("thread_id") is None]
        assert [row["external_id"] for row in provider_only] == ["500003"]
        assert data["counts"]["already_confirmed"] == 1
        assert data["counts"]["safe_exact_match"] == 1
        assert data["counts"]["unresolved"] == 1


class TestQueueThreadBootstrapCommit:
    """The commit surface must confirm exactly the approved bootstrap rows."""

    @pytest.mark.asyncio
    async def test_stale_preview_is_refused_when_state_changes(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """A plan change between preview and commit invalidates the preview token."""
        user = sample_data["user"]
        _, issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="Stale Bootstrap",
            issue_numbers=["1", "2"],
        )
        roster = [_roster_row(500001, "1"), _roster_row(500002, "2")]

        with _patch_comicvine(roster):
            preview = await auth_client.post(PREVIEW_URL, json=_bootstrap_payload(issues[0].id))
        assert preview.status_code == 200
        preview_data = preview.json()
        approved = _approvable_row_ids(preview_data["rows"])
        assert approved

        # A concurrent correction changes the bound plan state after the preview was minted.
        await _confirm_issue(async_db, issues[1], external_id="777777")

        with (
            _patch_comicvine(roster),
            patch("app.services.comicvine_fallback.refresh_issue_metadata", new=AsyncMock()),
        ):
            commit = await auth_client.post(
                COMMIT_URL,
                json={
                    "preview_token": preview_data["preview_token"],
                    "idempotency_key": "issue-3727-stale",
                    "approved_row_ids": approved,
                },
            )

        assert commit.status_code == 409
        assert commit.json()["detail"] == "preview_stale"

    @pytest.mark.asyncio
    async def test_commit_is_idempotent_for_a_repeated_request(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """Retrying the same commit key replays the stored result instead of rewriting."""
        user = sample_data["user"]
        _, issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="Idempotent Bootstrap",
            issue_numbers=["1", "2", "3"],
        )
        roster = [_roster_row(500000 + number, str(number)) for number in (1, 2, 3)]

        with _patch_comicvine(roster):
            preview = await auth_client.post(PREVIEW_URL, json=_bootstrap_payload(issues[0].id))
        assert preview.status_code == 200
        preview_data = preview.json()
        payload = {
            "preview_token": preview_data["preview_token"],
            "idempotency_key": "issue-3727-idempotent",
            "approved_row_ids": _approvable_row_ids(preview_data["rows"]),
        }

        with (
            _patch_comicvine(roster),
            patch("app.services.comicvine_fallback.refresh_issue_metadata", new=AsyncMock()),
        ):
            first = await auth_client.post(COMMIT_URL, json=payload)
            second = await auth_client.post(COMMIT_URL, json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["confirmed_issue_ids"] == second.json()["confirmed_issue_ids"]

    @pytest.mark.asyncio
    async def test_commit_refuses_rows_the_preview_did_not_mark_safe(
        self, auth_client: AsyncClient, async_db: AsyncSession, sample_data
    ) -> None:
        """An ambiguous bootstrap row cannot be bulk-approved even when its id is valid."""
        user = sample_data["user"]
        _, issues = await _create_thread_with_issues(
            async_db,
            user_id=user.id,
            title="Unsafe Bootstrap",
            issue_numbers=["1", "2"],
        )
        roster = [
            _roster_row(500001, "1"),
            _roster_row(500002, "2"),
            _roster_row(500003, "2"),
        ]

        with _patch_comicvine(roster):
            preview = await auth_client.post(PREVIEW_URL, json=_bootstrap_payload(issues[0].id))
        assert preview.status_code == 200
        preview_data = preview.json()
        ambiguous = next(
            row
            for row in preview_data["rows"]
            if row.get("issue_id") == issues[1].id and row.get("thread_id") is not None
        )
        assert ambiguous["classification"] == "needs_review_ambiguous"

        with _patch_comicvine(roster):
            commit = await auth_client.post(
                COMMIT_URL,
                json={
                    "preview_token": preview_data["preview_token"],
                    "idempotency_key": "issue-3727-unsafe",
                    "approved_row_ids": [str(ambiguous["row_id"])],
                },
            )

        assert commit.status_code == 422
        assert commit.json()["detail"] == "invalid_approved_row"
