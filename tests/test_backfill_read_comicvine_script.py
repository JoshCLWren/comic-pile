"""Regression tests for the read-comic ComicVine creator backfill operator CLI."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/backfill_read_comicvine.py"


def _module() -> ModuleType:
    """Import the operator CLI without treating scripts/ as a package."""
    module_name = "backfill_read_comicvine"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _issue(cli: ModuleType, **overrides: object) -> object:
    """Build one unmapped read issue with confirmed series evidence."""
    values: dict[str, object] = {
        "issue_id": 7,
        "thread_id": 3,
        "thread_title": "Example",
        "issue_number": "5",
        "position": 5,
        "identity_id": None,
        "external_id": None,
        "has_creator_credits": False,
        "has_person_credit_source": False,
        "creator_credit_count": 0,
        "series_identity_id": 99,
        "series_external_id": "4050-123",
        "series_volume_id": 123,
        "series_name": "Example",
    }
    values.update(overrides)
    return cli.ReadIssue(**values)


def test_script_does_not_import_application_database_or_settings() -> None:
    """The operator path must stay isolated from dotenv/Pydantic database selection."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "from app.database" not in source
    assert "import app.database" not in source
    assert "from app.config" not in source
    assert "from app.models" not in source


def test_database_url_comes_from_exported_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DATABASE_URL wins directly even when a different TEST_DATABASE_URL exists."""
    cli = _module()
    production = (
        "postgresql://owner:secret@ep-prod-pooler.example.neon.tech/neondb"
        "?sslmode=require&channel_binding=require"
    )
    monkeypatch.setenv("DATABASE_URL", production)
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/comic_pile_test",
    )
    monkeypatch.setenv("ENVIRONMENT", "test")

    assert cli._require_database_url(None) == production


def test_database_url_never_falls_back_to_test_or_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing DATABASE_URL is fatal even when the test URL is available."""
    cli = _module()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/comic_pile_test",
    )

    with pytest.raises(SystemExit, match="DATABASE_URL is required"):
        cli._require_database_url(None)


def test_neon_libpq_query_parameters_are_normalized_for_asyncpg() -> None:
    """Neon's sslmode/channel_binding URL works without hand-editing the env var."""
    cli = _module()

    normalized = cli._async_url(
        "postgresql://owner:secret@ep-prod-pooler.example.neon.tech/neondb"
        "?sslmode=require&channel_binding=require"
    )

    assert normalized.startswith("postgresql+asyncpg://")
    assert "ssl=require" in normalized
    assert "sslmode=" not in normalized
    assert "channel_binding=" not in normalized


def test_series_volume_id_falls_back_to_confirmed_series_external_identity() -> None:
    """Sparse series metadata can still use the stable ComicVine 4050 identity."""
    cli = _module()

    assert cli._series_volume_id(None, "4050-12345") == 12345
    assert cli._series_volume_id("999", "4050-12345") == 999


def test_creator_normalization_preserves_provider_ids_roles_and_empty_credits() -> None:
    """Deep ComicVine person credits become the shape creator analytics expects."""
    cli = _module()
    provider_row = {
        "id": 4005,
        "issue_number": "5",
        "person_credits": [
            {"id": 10, "name": "Writer Person", "role": "writer"},
            {"id": 20, "name": "Artist Person", "role": "penciler, inker"},
        ],
        "character_credits": [],
        "team_credits": [],
        "story_arc_credits": [],
    }

    metadata = cli._normalize_issue_metadata(provider_row)

    assert metadata["creator_credits"] == [
        {"id": 10, "name": "Writer Person", "role": "writer"},
        {"id": 20, "name": "Artist Person", "role": "penciler, inker"},
    ]
    assert cli._creator_credit_count(metadata) == 2

    empty_metadata = cli._normalize_issue_metadata(
        {
            "id": 4006,
            "issue_number": "6",
            "person_credits": [],
            "character_credits": [],
            "team_credits": [],
            "story_arc_credits": [],
        }
    )
    assert cli._creator_credit_count(empty_metadata) == 0


def test_read_issue_creator_state_distinguishes_local_repair_from_provider_fetch() -> None:
    """Inventory state keeps existing normalized and legacy-source cases separate."""
    cli = _module()

    normalized = _issue(
        cli,
        identity_id=10,
        external_id="4005",
        has_creator_credits=True,
        has_person_credit_source=True,
        creator_credit_count=3,
    )
    legacy = _issue(
        cli,
        identity_id=11,
        external_id="4006",
        has_creator_credits=False,
        has_person_credit_source=True,
        creator_credit_count=4,
    )

    assert normalized.has_creator_credits is True
    assert normalized.creator_credit_count == 3
    assert legacy.has_creator_credits is False
    assert legacy.has_person_credit_source is True
    assert legacy.creator_credit_count == 4


@pytest.mark.asyncio
async def test_inventory_and_local_creator_repair_use_real_postgres(
    async_db_committed: AsyncSession,
) -> None:
    """Legacy person credits are inventoried and merged without a provider request."""
    cli = _module()
    user = User(username="read-comicvine-backfill")
    async_db_committed.add(user)
    await async_db_committed.flush()
    thread = Thread(
        title="Creator Backfill Series",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="completed",
        user_id=user.id,
    )
    async_db_committed.add(thread)
    await async_db_committed.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="read",
    )
    series = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="4050-321",
        metadata_json={"name": "Creator Backfill Series"},
    )
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="654321",
        metadata_json={
            "id": 654321,
            "issue_number": "1",
            "description": "preserve me",
            "person_credits": [
                {"id": 10, "name": "Writer Person", "role": "writer"},
                {"id": 20, "name": "Artist Person", "role": "artist"},
            ],
        },
    )
    async_db_committed.add_all([issue, series, identity])
    await async_db_committed.flush()
    async_db_committed.add_all(
        [
            IssueExternalIdentityMapping(
                issue_id=issue.id,
                external_identity_id=identity.id,
                status="confirmed",
                confidence=1.0,
            ),
            ThreadExternalSeriesMapping(
                thread_id=thread.id,
                external_identity_id=series.id,
                status="confirmed",
                confidence=1.0,
            ),
        ]
    )
    await async_db_committed.commit()

    rows = await cli._load_read_issues(
        async_db_committed,
        user_id=user.id,
        limit=None,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.has_creator_credits is False
    assert row.has_person_credit_source is True
    assert row.creator_credit_count == 2
    assert row.series_volume_id == 321

    count = await cli._normalize_existing_creator_credits(
        async_db_committed,
        identity_id=identity.id,
    )
    await async_db_committed.refresh(identity)

    assert count == 2
    assert identity.metadata_json["description"] == "preserve me"
    assert identity.metadata_json["creator_credits"] == identity.metadata_json["person_credits"]


@pytest.mark.asyncio
async def test_unmapped_resolution_requires_one_exact_numeric_volume_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The backfill confirms only one exact issue-number match inside the confirmed volume."""
    cli = _module()
    issue = _issue(cli)

    class FakeClient:
        """Return a deterministic volume roster."""

        async def fetch_volume_issues(self, volume_id: int) -> list[dict[str, object]]:
            assert volume_id == 123
            return [
                {"id": 4004, "issue_number": "4", "volume": {"id": 123}},
                {"id": 4005, "issue_number": "5", "volume": {"id": 123}},
                {"id": 4006, "issue_number": "6", "volume": {"id": 123}},
            ]

    persist = AsyncMock(return_value=(55, "4005"))
    monkeypatch.setattr(cli, "_persist_resolved_mapping", persist)

    result = await cli._resolve_unmapped_issue(
        object(),
        FakeClient(),
        user_id=1,
        issue=issue,
    )

    assert result == (55, "4005")
    persist.assert_awaited_once()
    assert persist.call_args.kwargs["provider_row"]["id"] == 4005


@pytest.mark.asyncio
async def test_unmapped_resolution_refuses_ambiguous_duplicate_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two provider rows with the same issue number remain unresolved."""
    cli = _module()
    issue = _issue(cli)

    class FakeClient:
        """Return an ambiguous ComicVine volume roster."""

        async def fetch_volume_issues(self, volume_id: int) -> list[dict[str, object]]:
            assert volume_id == 123
            return [
                {"id": 4005, "issue_number": "5", "volume": {"id": 123}},
                {"id": 4999, "issue_number": "5", "volume": {"id": 123}},
            ]

    persist = AsyncMock()
    monkeypatch.setattr(cli, "_persist_resolved_mapping", persist)

    result = await cli._resolve_unmapped_issue(
        object(),
        FakeClient(),
        user_id=1,
        issue=issue,
    )

    assert result is None
    persist.assert_not_awaited()
