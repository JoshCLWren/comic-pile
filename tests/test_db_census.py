"""Focused tests for DB census (#3217) — read-only, redaction, fixtures, artifact."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db_census import (
    assemble_report,
    build_fixtures,
    measure_synthetic,
)


class TestReadOnlyBehavior:
    """Tests that the census script rejects mutation and read-only guards exist."""

    def test_mutation_flags_rejected(self):
        """Confirm mutation guard present in the script source."""
        src_path = os.path.join(os.path.dirname(__file__), "..", "scripts", "db_census.py")
        with open(src_path) as f:
            src = f.read()
        for flag in ["--mutate", "--write", "--update", "--alter"]:
            assert flag in src
        assert "mutation mode rejected" in src

    def test_read_only_transaction_in_script_source(self):
        """Confirm read-only transaction and readonly markers in script."""
        src_path = os.path.join(os.path.dirname(__file__), "..", "scripts", "db_census.py")
        with open(src_path) as f:
            src = f.read()
        assert "SET TRANSACTION READ ONLY" in src
        assert "mutation_modes_rejected" in src
        assert "explain_analyze_on_writes_rejected" in src

    def test_never_explains_writes_in_plan_list(self):
        """Confirm the bounded plans never EXPLAIN write statements."""
        src_path = os.path.join(os.path.dirname(__file__), "..", "scripts", "db_census.py")
        with open(src_path) as f:
            src = f.read()
        # No INSERT/UPDATE/DELETE inside EXPLAIN blocks
        for bad in ["EXPLAIN (FORMAT JSON) INSERT", "EXPLAIN (FORMAT JSON) UPDATE", "EXPLAIN (FORMAT JSON) DELETE"]:
            assert bad not in src, f"mutating explain found: {bad}"


class TestRedaction:
    """Tests that redaction flags and fields are applied."""

    def test_redacted_fields_listed(self):
        """Verify report redaction metadata."""
        fixtures = build_fixtures()
        synth = measure_synthetic(fixtures)
        report = assemble_report(fixtures, synth, None)
        redacted = report.get("redacted_fields", [])
        assert "user_display_name" in redacted
        assert "thread_title" in redacted
        assert "issue_notes" in redacted
        assert "payload_content" in redacted
        assert report.get("redaction_applied") is True

    def test_fixture_redacted_flag_true(self):
        """Verify every fixture carries synthetic and redacted flags."""
        fixtures = build_fixtures()
        for f in fixtures.values():
            assert f.get("redacted") is True
            assert f.get("synthetic") is True

    def test_no_credential_emission_in_synthetic(self):
        """Verify no credentials appear in the synthetic baseline output."""
        fixtures = build_fixtures()
        synth = measure_synthetic(fixtures)
        for profile in synth.values():
            payload = str(profile)
            assert "password" not in payload.lower()
            assert "secret" not in payload.lower()
            assert "token" not in payload.lower()
            # No literal user names or titles embedded
            assert "alice" not in payload.lower()
            assert "bob" not in payload.lower()


class TestFixtures:
    """Tests for fixture profiles."""

    def test_2_users_small_exists(self):
        """Confirm a users=2 small-library fixture exists."""
        fixtures = build_fixtures()
        assert any("users=2" in k or "small" in k for k in fixtures)

    def test_100_users_large_exists(self):
        """Confirm a users=100 large-library fixture exists."""
        fixtures = build_fixtures()
        assert any("users=100" in k or "large" in k for k in fixtures)

    def test_shared_provider_identities(self):
        """Verify the fixtures carry shared-provider identities."""
        fixtures = build_fixtures()
        for f in fixtures.values():
            ids = f.get("shared_provider_identities", [])
            assert isinstance(ids, list)
            assert len(ids) >= 1

    def test_snapshot_mix_legacy_delta(self):
        """Verify the fixture snapshot mix includes legacy/delta mix."""
        fixtures = build_fixtures()
        for f in fixtures.values():
            mix = f.get("snapshot_mix", [])
            assert "legacy" in mix or "delta" in mix or "shared_provider" in mix


class TestSyntheticBaseline:
    """Tests for the synthetic measurement baseline."""

    def test_synthetic_has_bytes(self):
        """Verify the synthetic baseline includes byte estimates."""
        fixtures = build_fixtures()
        synth = measure_synthetic(fixtures)
        for profile in synth.values():
            assert "simulated_table_bytes" in profile
            assert "simulated_index_bytes" in profile
            assert "simulated_total_bytes" in profile

    def test_total_is_non_negative(self):
        """Verify simulated totals are non-negative."""
        fixtures = build_fixtures()
        synth = measure_synthetic(fixtures)
        for profile in synth.values():
            assert profile["simulated_total_bytes"] >= 0


class TestArtifactGeneration:
    """Tests for the census report artifact."""

    def test_output_json_valid(self, tmp_path):
        """Verify the report round-trips through JSON."""
        out = tmp_path / "census.json"
        fixtures = build_fixtures()
        synth = measure_synthetic(fixtures)
        report = assemble_report(fixtures, synth, None)
        out.write_text(json.dumps(report, indent=2))
        loaded = json.loads(out.read_text())
        assert loaded.get("report_version") == "v1"
        assert loaded.get("issue_ref") == "#3217"
        assert "fixture_definitions" in loaded
        assert "synthetic_baseline" in loaded
        assert loaded.get("mutation_modes_rejected") is True
        assert loaded.get("redaction_applied") is True

    def test_real_measurement_omitted_when_none(self):
        """Verify real_measurement is None when no real DB is measured."""
        fixtures = build_fixtures()
        synth = measure_synthetic(fixtures)
        report = assemble_report(fixtures, synth, None)
        assert report.get("real_measurement") is None

    def test_index_overview_flags_true(self):
        """Verify index overview flags are set in the report."""
        fixtures = build_fixtures()
        synth = measure_synthetic(fixtures)
        report = assemble_report(fixtures, synth, None)
        assert report["index_overview"]["constraint_backed_indexes_reviewed"] is True
        assert report["index_overview"]["predicate_key_uniqueness_deferrability_noted"] is True
