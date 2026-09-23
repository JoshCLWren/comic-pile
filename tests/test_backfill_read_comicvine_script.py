"""Regression tests for the read-comic ComicVine creator backfill operator CLI."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Protocol
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)


class _ReadIssueLike(Protocol):
    """Structural shape of the operator's ``ReadIssue`` dataclass."""

    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    position: int
    identity_id: int | None
    external_id: str | None
    has_creator_credits: bool
    has_person_credit_source: bool
    creator_credit_count: int
    series_identity_id: int | None
    series_external_id: str | None
    series_volume_id: int | None
    series_name: str | None


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


def _issue(cli: ModuleType, **overrides: object) -> _ReadIssueLike:
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


class _NoProviderClient:
    """Fail loudly if the operator reaches ComicVine on a local-only path."""

    async def fetch_issue(self, provider_id: int, *, refresh: bool = False) -> object:
        raise AssertionError(f"unexpected provider fetch for issue {provider_id}")

    async def fetch_volume_issues(self, volume_id: int) -> list[dict[str, object]]:
        raise AssertionError(f"unexpected provider roster fetch for volume {volume_id}")


class _NoMutationDb:
    """Fail loudly if dry-run or already-complete work touches the database."""

    async def execute(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("unexpected database execute during read-only path")

    async def scalar(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("unexpected database scalar during read-only path")

    async def commit(self) -> None:
        raise AssertionError("unexpected database commit during read-only path")

    async def rollback(self) -> None:
        raise AssertionError("unexpected database rollback during read-only path")


@pytest.mark.asyncio
async def test_completed_work_is_resumable_without_provider_or_mutation() -> None:
    """Re-running finished creator work neither fetches nor writes."""
    cli = _module()
    issue = _issue(
        cli,
        identity_id=10,
        external_id="4005",
        has_creator_credits=True,
        has_person_credit_source=True,
        creator_credit_count=3,
    )

    result = await cli._process_issue(
        _NoMutationDb(),
        _NoProviderClient(),
        user_id=1,
        issue=issue,
        dry_run=False,
        refresh=False,
    )

    assert result.status == "complete"
    assert result.comicvine_issue_id == "4005"
    assert result.creator_credits == 3


@pytest.mark.asyncio
async def test_dry_run_performs_no_mutation_and_no_provider_request() -> None:
    """Dry-run only classifies inventory state; it never writes or fetches."""
    cli = _module()
    needs_hydration = _issue(
        cli,
        identity_id=10,
        external_id="4005",
        has_creator_credits=False,
        has_person_credit_source=False,
        creator_credit_count=0,
    )
    needs_normalization = _issue(
        cli,
        identity_id=11,
        external_id="4006",
        has_creator_credits=False,
        has_person_credit_source=True,
        creator_credit_count=2,
    )
    unmapped = _issue(cli)

    hydration = await cli._process_issue(
        _NoMutationDb(),
        _NoProviderClient(),
        user_id=1,
        issue=needs_hydration,
        dry_run=True,
        refresh=False,
    )
    normalization = await cli._process_issue(
        _NoMutationDb(),
        _NoProviderClient(),
        user_id=1,
        issue=needs_normalization,
        dry_run=True,
        refresh=False,
    )
    unmapped_result = await cli._process_issue(
        _NoMutationDb(),
        _NoProviderClient(),
        user_id=1,
        issue=unmapped,
        dry_run=True,
        refresh=False,
    )

    assert hydration.status == "needs-hydration"
    assert normalization.status == "needs-normalization"
    assert unmapped_result.status == "unmapped"


@pytest.mark.asyncio
async def test_locally_satisfiable_creator_work_makes_no_provider_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stored person_credits normalize locally without a ComicVine request."""
    cli = _module()
    issue = _issue(
        cli,
        identity_id=12,
        external_id="4007",
        has_creator_credits=False,
        has_person_credit_source=True,
        creator_credit_count=2,
    )

    normalize = AsyncMock(return_value=2)
    monkeypatch.setattr(cli, "_normalize_existing_creator_credits", normalize)

    class _LocalOnlyDb:
        """Session stand-in for the local-normalization commit path."""

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            raise AssertionError("local normalization should commit, not roll back")

    result = await cli._process_issue(
        _LocalOnlyDb(),
        _NoProviderClient(),
        user_id=1,
        issue=issue,
        dry_run=False,
        refresh=False,
    )

    assert result.status == "complete"
    assert result.creator_credits == 2
    normalize.assert_awaited_once()
    assert normalize.call_args.kwargs["identity_id"] == 12


@pytest.mark.asyncio
async def test_local_snapshot_proves_identity_before_provider_work() -> None:
    """A complete local roster resolves an issue without a provider client."""
    cli = _module()
    issue = _issue(cli, series_volume_id=123)

    class Snapshot:
        available = True
        path = Path("localcv.db")

        def get_volume_issues(self, volume_id: int) -> list[SimpleNamespace]:
            assert volume_id == 123
            return [
                SimpleNamespace(
                    data={
                        "id": 4005,
                        "issue_number": "5",
                        "name": "Example",
                        "volume": {"id": 123, "name": "Example"},
                    }
                )
            ]

    candidate = await cli._resolve_local_identity(
        object(),
        Snapshot(),
        user_id=1,
        issue=issue,
        roster_cache={},
        dry_run=True,
    )

    assert candidate is not None
    assert candidate.external_id == "4005"
    assert candidate.volume_id == 123
    assert candidate.source == "comicvine-local-sqlite"


@pytest.mark.asyncio
async def test_local_creator_phase_persists_sqlite_credits_without_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local creator hydration is complete without accepting a provider dependency."""
    cli = _module()
    issue = _issue(
        cli,
        identity_id=10,
        external_id="4005",
        has_creator_credits=False,
        has_person_credit_source=False,
    )
    local_payload = {"id": 4005, "person_credits": [{"id": 1, "name": "Writer"}]}
    monkeypatch.setattr(cli, "_local_creator_payload", AsyncMock(return_value=local_payload))
    persist = AsyncMock(return_value=1)
    monkeypatch.setattr(cli, "_persist_deep_metadata", persist)

    class Snapshot:
        available = True
        path = Path("localcv.db")

    database = object()
    result = await cli._process_local_creator_issue(
        database,
        Snapshot(),
        issue=issue,
        dry_run=False,
        refresh=False,
    )

    assert result.status == "complete"
    assert result.provenance == "comicvine-local-sqlite"
    persist.assert_awaited_once_with(
        database,
        identity_id=10,
        provider_result=local_payload,
    )


@pytest.mark.asyncio
async def test_pipeline_runs_four_stages_in_local_first_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The public command records all four stages before any provider stage."""
    cli = _module()
    events: list[str] = []

    class Snapshot:
        available = False
        path = None

    class Session:
        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    class Engine:
        async def dispose(self) -> None:
            return None

    async def local_identity(*args: object, **kwargs: object) -> list[object]:
        events.append("local-identity")
        return []

    async def local_creators(*args: object, **kwargs: object) -> list[object]:
        events.append("local-creators")
        return []

    async def provider_identity(*args: object, **kwargs: object) -> list[object]:
        events.append("provider-identity")
        return []

    async def provider_creators(*args: object, **kwargs: object) -> list[object]:
        events.append("provider-creators")
        return []

    monkeypatch.setattr(cli, "_local_snapshot_from_environment", lambda: Snapshot())
    monkeypatch.setattr(cli, "_user_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(cli, "_load_read_issues", AsyncMock(return_value=[]))
    monkeypatch.setattr(cli, "_engine", lambda database_url: Engine())
    monkeypatch.setattr(
        cli,
        "async_sessionmaker",
        lambda *args, **kwargs: lambda **session_kwargs: Session(),
    )
    monkeypatch.setattr(cli, "_run_local_identity_phase", local_identity)
    monkeypatch.setattr(cli, "_run_local_creator_phase", local_creators)
    monkeypatch.setattr(cli, "_run_provider_identity_phase", provider_identity)
    monkeypatch.setattr(cli, "_run_provider_creator_phase", provider_creators)

    args = argparse.Namespace(
        user_id=1,
        database_url="postgresql://owner:secret@example.invalid/neondb",
        dry_run=True,
        refresh=False,
        limit=None,
        report=tmp_path / "report.json",
    )
    exit_code = await cli._run(args)

    assert exit_code == 0
    assert events == [
        "local-identity",
        "local-creators",
        "provider-identity",
        "provider-creators",
    ]
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert [phase["name"] for phase in report["phases"]] == [
        "local-identity",
        "local-creators",
        "provider-identity",
        "provider-creators",
    ]
    assert all(phase["provider_requests"] == 0 for phase in report["phases"])


@pytest.mark.asyncio
async def test_provider_identity_throttle_defers_one_resource_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A throttled identity resource does not stop unrelated provider work."""
    cli = _module()
    first = _issue(cli, issue_id=1)
    second = _issue(cli, issue_id=2, series_volume_id=None, series_external_id=None)

    async def resolve(*args: object, **kwargs: object) -> tuple[int, str]:
        issue = kwargs["issue"]
        if issue.issue_id == 1:
            raise cli.ComicVineRateLimitError("issues cooling", resource="issues")
        return (99, "4002")

    monkeypatch.setattr(cli, "_resolve_provider_issue", resolve)
    results = await cli._run_provider_identity_phase(
        object(),
        object(),
        user_id=1,
        issues=[first, second],
        dry_run=False,
    )

    assert [result.status for result in results] == ["rate-limited", "resolved-provider"]
    assert results[0].resource == "issues"
