"""Tests for the deterministic census fixture generator (issue #3217)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.generate_census_fixtures import (
    CENSUS_SCENARIOS,
    build_scenario,
    main,
    write_fixtures,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "docs/database-census/fixtures"

class TestScenarioCoverage:
    """The issue contract names the scenarios that must exist."""
    @pytest.mark.parametrize(
        "user_count",
        [2, 100],
        ids=["two_users", "one_hundred_users"],
    )
    def test_small_and_large_reader_populations_exist(self, user_count: int) -> None:
        """Small and large reader populations exist."""
        assert any(
            scenario["user_count"] == user_count
            for scenario in CENSUS_SCENARIOS.values()
        )

    def test_scenarios_cover_small_and_large_libraries(self) -> None:
        """Scenarios cover small and large libraries."""
        thread_counts = sorted(s["thread_count"] for s in CENSUS_SCENARIOS.values())
        assert thread_counts[0] < thread_counts[-1]

    def test_every_scenario_has_mixed_legacy_and_delta_snapshots(self) -> None:
        """Every scenario has mixed legacy and delta snapshots."""
        for name, scenario in CENSUS_SCENARIOS.items():
            assert 0 < scenario["legacy_snapshot_count"] < scenario["snapshot_count"], name

    def test_every_scenario_has_shared_provider_identities(self) -> None:
        """Every scenario has shared provider identities."""
        for name, scenario in CENSUS_SCENARIOS.items():
            assert scenario["shared_provider_identity_count"] > 0, name

    def test_scenario_counts_are_self_consistent(self) -> None:
        """Scenario counts are self consistent."""
        for name, scenario in CENSUS_SCENARIOS.items():
            assert scenario["issue_count"] >= scenario["thread_count"], name
            assert scenario["snapshot_count"] >= scenario["legacy_snapshot_count"], name

class TestDeterminism:
    """Fixture output must be byte-identical on every run."""
    @pytest.mark.parametrize("name", sorted(CENSUS_SCENARIOS))
    def test_scenario_is_reproducible(self, name: str) -> None:
        """Scenario is reproducible."""
        assert build_scenario(name) == build_scenario(name)

    def test_written_fixtures_are_stable(self, tmp_path: Path) -> None:
        """Written fixtures are stable."""
        first = write_fixtures(tmp_path / "first")
        second = write_fixtures(tmp_path / "second")

        for left, right in zip(first, second, strict=True):
            assert left.name == right.name
            assert left.read_bytes() == right.read_bytes()

    def test_no_wall_clock_timestamp_is_embedded(self) -> None:
        """No wall clock timestamp is embedded."""
        for name in CENSUS_SCENARIOS:
            collected_at = build_scenario(name)["metadata"]["collected_at"]
            assert collected_at == "2026-01-01T00:00:00+00:00"

class TestFixtureShape:
    """Fixtures must be usable as census report stand-ins."""
    @pytest.mark.parametrize("name", sorted(CENSUS_SCENARIOS))
    def test_reports_are_complete_and_marked_synthetic(self, name: str) -> None:
        """Reports are complete and marked synthetic."""
        report = build_scenario(name)

        assert report["synthetic"] is True
        assert {
            "report_version",
            "metadata",
            "storage",
            "tables",
            "indexes",
            "snapshots",
            "queries",
            "constraints",
        } <= set(report)
        assert report["metadata"]["read_only_transaction"] is True

    @pytest.mark.parametrize("name", sorted(CENSUS_SCENARIOS))
    def test_index_flags_never_claim_a_confirmed_removal(self, name: str) -> None:
        """Index flags never claim a confirmed removal."""
        for entry in build_scenario(name)["indexes"]["potential_redundant_indexes"]:
            assert entry["classification"] == "potential_redundant"
            assert entry["confirmed_safe_removal"] is False

    @pytest.mark.parametrize("name", sorted(CENSUS_SCENARIOS))
    def test_fixtures_carry_no_user_data(self, name: str) -> None:
        """Fixtures carry no user data."""
        serialized = json.dumps(build_scenario(name))

        for forbidden in ("password", "email", "notes", "title"):
            assert forbidden not in serialized, forbidden

    @pytest.mark.parametrize("name", sorted(CENSUS_SCENARIOS))
    def test_measured_rows_match_declared_counts(self, name: str) -> None:
        """Measured rows match declared counts."""
        report = build_scenario(name)

        assert (
            report["tables"]["threads"]["measured_rows"]
            == CENSUS_SCENARIOS[name]["thread_count"]
        )
        assert (
            report["tables"]["issues"]["measured_rows"]
            == CENSUS_SCENARIOS[name]["issue_count"]
        )

class TestCommittedFixtures:
    """The published baseline must match the generator byte for byte."""
    def test_every_scenario_is_published_under_docs(self) -> None:
        """Every scenario is published under docs."""
        published = sorted(path.name for path in FIXTURE_DIR.glob("*.json"))

        assert published == [f"census_{name}.json" for name in sorted(CENSUS_SCENARIOS)]

    @pytest.mark.parametrize("name", sorted(CENSUS_SCENARIOS))
    def test_published_fixture_matches_the_generator(self, name: str) -> None:
        """Published fixture matches the generator."""
        path = FIXTURE_DIR / f"census_{name}.json"

        assert json.loads(path.read_text(encoding="utf-8")) == build_scenario(name), (
            f"{path.name} is stale; rerun `python -m scripts.generate_census_fixtures "
            "--output-dir docs/database-census/fixtures`"
        )

class TestCommand:
    """The generator is runnable as a documented command."""
    def test_writes_every_scenario(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Writes every scenario."""
        exit_code = main(["--output-dir", str(tmp_path)])

        assert exit_code == 0
        written = sorted(path.name for path in tmp_path.glob("*.json"))
        assert written == [f"census_{name}.json" for name in sorted(CENSUS_SCENARIOS)]
        assert len(capsys.readouterr().out.splitlines()) == len(CENSUS_SCENARIOS)

    def test_unknown_scenario_is_rejected(self) -> None:
        """Unknown scenario is rejected."""
        with pytest.raises(KeyError):
            build_scenario("not_a_scenario")

    def test_fixture_files_round_trip_as_json(self, tmp_path: Path) -> None:
        """Fixture files round trip as json."""
        for path in write_fixtures(tmp_path):
            assert json.loads(path.read_text(encoding="utf-8"))["synthetic"] is True
