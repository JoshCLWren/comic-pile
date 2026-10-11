"""Tests for the database census CLI command (issue #3217)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.database_census import (
    build_parser,
    main,
    run_census,
    synthetic_report,
    write_report,
)
from app.services.database_census_service import CENSUS_REPORT_VERSION

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

def _synthetic_scenarios() -> set[str]:
    return {
        "report_version",
        "metadata",
        "storage",
        "tables",
        "indexes",
        "snapshots",
        "queries",
        "constraints",
    }

class TestSyntheticDefault:
    """Creating tooling must never authorize running it against production."""

    async def test_defaults_to_synthetic_without_a_database_url(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Defaults to synthetic without a database url."""
        output = tmp_path / "census.json"

        exit_code = await main(["--output", str(output)])

        assert exit_code == 0
        assert capsys.readouterr().out == ""
        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["synthetic"] is True
        assert report["metadata"]["postgresql_version"] == "synthetic"

    async def test_synthetic_flag_wins_over_database_url(
        self, tmp_path: Path
    ) -> None:
        """Synthetic flag wins over database url."""
        output = tmp_path / "census.json"

        exit_code = await main(
            ["--synthetic", "--database-url", "postgresql+asyncpg://nope/nope", "--output", str(output)]
        )

        assert exit_code == 0
        assert json.loads(output.read_text(encoding="utf-8"))["synthetic"] is True

    async def test_writes_synthetic_report_to_stdout(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Writes synthetic report to stdout."""
        exit_code = await main([])

        assert exit_code == 0
        report = json.loads(capsys.readouterr().out)
        assert report["report_version"] == CENSUS_REPORT_VERSION

    def test_synthetic_report_has_the_full_shape(self) -> None:
        """Synthetic report has the full shape."""
        assert _synthetic_scenarios() <= set(synthetic_report())

    def test_synthetic_report_is_deterministic(self) -> None:
        """Synthetic report is deterministic."""
        assert synthetic_report() == synthetic_report()

class TestReportWriting:
    """Reports must be reproducible bytes on disk."""

    def test_creates_missing_parent_directories(self, tmp_path: Path) -> None:
        """Creates missing parent directories."""
        destination = tmp_path / "nested" / "dir" / "census.json"

        write_report(synthetic_report(), str(destination))

        assert destination.exists()

    def test_serialized_output_is_stable(self, tmp_path: Path) -> None:
        """Serialized output is stable."""
        first = tmp_path / "first.json"
        second = tmp_path / "second.json"

        write_report(synthetic_report(), str(first))
        write_report(synthetic_report(), str(second))

        assert first.read_bytes() == second.read_bytes()

    def test_ends_with_a_trailing_newline(self, tmp_path: Path) -> None:
        """Ends with a trailing newline."""
        destination = tmp_path / "census.json"

        write_report(synthetic_report(), str(destination))

        assert destination.read_text(encoding="utf-8").endswith("}\n")

class TestArgumentParsing:
    """The CLI surface is part of the read-only contract."""

    def test_database_url_is_never_inferred(self) -> None:
        """Database url is never inferred."""
        args = build_parser().parse_args([])

        assert args.database_url is None
        assert args.synthetic is False

    def test_accepts_bounded_collection_options(self) -> None:
        """Accepts bounded collection options."""
        args = build_parser().parse_args(
            ["--timeout", "5", "--sample-limit", "2", "--database-url", "url"]
        )

        assert args.timeout == 5
        assert args.sample_limit == 2
        assert args.database_url == "url"

    def test_defaults_are_bounded(self) -> None:
        """Defaults are bounded."""
        args = build_parser().parse_args([])

        assert args.timeout > 0
        assert args.sample_limit > 0

class TestRunCensusAgainstASuppliedDatabase:
    """An explicitly supplied URL is the only path that touches a database."""

    async def test_runs_read_only_against_postgres(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Runs read only against postgres."""
        from tests.conftest import get_test_database_url

        report = await run_census(
            database_url=get_test_database_url(),
            timeout_seconds=60,
            sample_limit=2,
        )

        assert report["report_version"] == CENSUS_REPORT_VERSION
        assert report["metadata"]["read_only_transaction"] is True
        assert report["metadata"]["postgresql_version"].startswith("PostgreSQL")
        assert report["metadata"]["statement_timeout_seconds"] == 60
        assert report["storage"]["tables"]

    async def test_rejects_invalid_timeout_before_connecting(self) -> None:
        """Rejects invalid timeout before connecting."""
        with pytest.raises(ValueError, match="timeout_seconds"):
            await run_census(database_url="postgresql+asyncpg://x/y", timeout_seconds=0)

    async def test_writes_report_to_the_requested_file(self, tmp_path: Path) -> None:
        """Writes report to the requested file."""
        from tests.conftest import get_test_database_url

        destination = tmp_path / "measured.json"
        await run_census(
            database_url=get_test_database_url(),
            output_file=str(destination),
            timeout_seconds=60,
            sample_limit=2,
        )

        assert json.loads(destination.read_text(encoding="utf-8"))["storage"]["tables"]

    async def test_reports_a_connection_failure_as_a_nonzero_exit(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Reports a connection failure as a nonzero exit."""
        exit_code = await main(
            ["--database-url", "postgresql+asyncpg://nobody@127.0.0.1:1/does_not_exist"]
        )

        assert exit_code == 1
        assert "census failed" in capsys.readouterr().err
