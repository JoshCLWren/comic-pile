"""Regression tests for the production schema audit (issue #4735)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.export_roll_test_schema import (
    FIXTURE_PATH,
    _compare_normalized_schemas,
    _normalize_catalog,
    _redact,
    _split_statements,
)
from scripts.production_schema_audit import _child_env, _parse_dsn

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/production-schema-audit.yml"
FIXTURE_TEXT = FIXTURE_PATH.read_text(encoding="utf-8")

MINIMAL_SCHEMA = """\
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: threads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.threads (
    id integer NOT NULL,
    title character varying(200) NOT NULL
);


--
-- Name: threads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.threads
    ADD CONSTRAINT threads_pkey PRIMARY KEY (id);
"""


def _reordered(schema: str) -> str:
    """Return the same schema with statement units in reverse order."""
    units = _split_statements(schema)
    return "\n\n".join(reversed(units)) + "\n"


def test_normalize_catalog_is_order_insensitive() -> None:
    """Harmless pg_dump ordering differences must not report as drift."""
    assert _normalize_catalog(_reordered(MINIMAL_SCHEMA)) == _normalize_catalog(
        MINIMAL_SCHEMA
    )
    assert _compare_normalized_schemas(MINIMAL_SCHEMA, _reordered(MINIMAL_SCHEMA)) == {
        "added": [],
        "removed": [],
        "changed": [],
    }


def test_normalize_catalog_is_idempotent() -> None:
    """Canonical form must be a fixed point, including for the full fixture."""
    canonical = _normalize_catalog(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert _normalize_catalog(canonical) == canonical


def test_added_column_is_detected_as_changed() -> None:
    """A throwaway added column must fail the audit comparison."""
    mutated = MINIMAL_SCHEMA.replace(
        "title character varying(200) NOT NULL",
        "title character varying(200) NOT NULL,\n    audit_probe integer",
    )
    comparison = _compare_normalized_schemas(MINIMAL_SCHEMA, mutated)
    assert comparison["changed"] == ["TABLE threads"]
    assert comparison["added"] == []
    assert comparison["removed"] == []


def test_dropped_index_is_detected() -> None:
    """Dropping an index must surface as a removal, not be normalized away."""
    with_index = MINIMAL_SCHEMA + (
        "\n-- Name: ix_threads_title; Type: INDEX; Schema: public; Owner: -\n--\n\n"
        "CREATE INDEX ix_threads_title ON public.threads USING btree (title);\n"
    )
    comparison = _compare_normalized_schemas(with_index, MINIMAL_SCHEMA)
    assert comparison["removed"] == ["INDEX ix_threads_title"]
    assert comparison["added"] == []


def test_added_constraint_is_detected() -> None:
    """An added constraint must surface as an addition."""
    mutated = MINIMAL_SCHEMA + (
        "\n-- Name: threads_title_length_check; Type: CONSTRAINT; "
        "Schema: public; Owner: -\n--\n\n"
        "ALTER TABLE ONLY public.threads ADD CONSTRAINT threads_title_length_check "
        "CHECK (char_length(title) > 0);\n"
    )
    comparison = _compare_normalized_schemas(MINIMAL_SCHEMA, mutated)
    assert comparison["added"] == ["CONSTRAINT threads_title_length_check"]


def test_function_body_change_is_preserved() -> None:
    """Function body changes must not be masked by normalization."""
    function = (
        "-- Name: noop(); Type: FUNCTION; Schema: public; Owner: -\n--\n\n"
        "CREATE FUNCTION public.noop() RETURNS void LANGUAGE plpgsql AS $$\n"
        "BEGIN\n    RETURN;\nEND;\n$$;\n"
    )
    mutated = function.replace("RETURN;", "RAISE EXCEPTION 'changed';")
    comparison = _compare_normalized_schemas(function, mutated)
    assert comparison["changed"] == ["FUNCTION noop()"]


def test_array_cast_deparse_variants_compare_equal() -> None:
    """Newer/older ruleutils ARRAY-cast spellings must not report as drift."""
    older = (
        "-- Name: t; Type: TABLE; Schema: public; Owner: -\n--\n\n"
        "CREATE TABLE public.t (s character varying(20) "
        "CONSTRAINT ck CHECK (((s)::text = ANY "
        "((ARRAY['a'::character varying, 'b'::character varying])::text[]))));\n"
    )
    newer = (
        "-- Name: t; Type: TABLE; Schema: public; Owner: -\n--\n\n"
        "CREATE TABLE public.t (s character varying(20) "
        "CONSTRAINT ck CHECK (((s)::text = ANY "
        "(ARRAY[('a'::character varying)::text, ('b'::character varying)::text]))));\n"
    )
    comparison = _compare_normalized_schemas(older, newer)
    assert comparison == {"added": [], "removed": [], "changed": []}
    # Same position, different membership: a real change, never masked.
    altered = newer.replace("'b'", "'c'")
    drift = _compare_normalized_schemas(older, altered)
    assert drift["changed"] == ["TABLE t"]


def test_extension_drift_is_categorized_and_allowlist_is_narrow() -> None:
    """Prod-only extensions are flagged by category until deliberately allowed."""
    mutated = MINIMAL_SCHEMA + (
        "CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public;\n"
    )
    plain = _compare_normalized_schemas(MINIMAL_SCHEMA, mutated)
    assert plain["added"] == [
        "EXTENSION CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public;"
    ]
    allowed = _compare_normalized_schemas(
        MINIMAL_SCHEMA, mutated, frozenset({"pg_stat_statements"})
    )
    assert allowed == {"added": [], "removed": [], "changed": []}
    other = _compare_normalized_schemas(
        MINIMAL_SCHEMA, mutated, frozenset({"pg_cron"})
    )
    assert len(other["added"]) == 1


def test_dsn_parsing_and_child_env_keep_password_out_of_argv() -> None:
    """The password travels via PGPASSWORD only; sessions are read-only."""
    dsn = "postgresql://schema_audit:s3cret-pw@ep-test.neon.tech/app?sslmode=require"
    properties = _parse_dsn(dsn)
    assert properties["host"] == "ep-test.neon.tech"
    assert properties["database"] == "app"
    assert properties["user"] == "schema_audit"
    env = _child_env(properties)
    assert env["PGPASSWORD"] == "s3cret-pw"
    assert env["PGHOST"] == "ep-test.neon.tech"
    assert "default_transaction_read_only=on" in env["PGOPTIONS"]
    assert "statement_timeout=60000" in env["PGOPTIONS"]
    assert env["PGCONNECT_TIMEOUT"] == "10"
    assert env["PGSSLMODE"] == "require"
    # Without sslmode in the DSN, libpq must not hard-require SSL and thereby
    # exclude local throwaway databases from auditable round-trips.
    default_env = _child_env(_parse_dsn("postgresql://u:p@h/db"))
    assert default_env["PGSSLMODE"] == "prefer"
    redacted = _redact(f"failed connecting {dsn} with s3cret-pw", [dsn, "s3cret-pw"])
    assert "s3cret-pw" not in redacted
    assert dsn not in redacted


def test_audit_script_never_places_dsn_or_password_in_argv() -> None:
    """The subprocess call must use env-only transport (no argv credential)."""
    source = (REPO_ROOT / "scripts/production_schema_audit.py").read_text(
        encoding="utf-8"
    )
    assert '"pg_dump"' in source
    assert "PGPASSWORD" in source
    # The argv list literal must contain only pg_dump flags; the credential
    # travels via the env mapping, never as an argv element.
    assert '                "--no-comments",\n            ],' in source
    assert "env=env," in source
    # Only the env-var name flag exists; the URL itself is never a CLI arg.
    assert '"--database-url"' not in source


def test_workflow_is_safe_and_read_only() -> None:
    """The scheduled workflow must be secret-safe and least-privilege."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    # pull_request_target may only be mentioned in a comment explaining that
    # this workflow deliberately avoids it.
    for line in workflow.splitlines():
        if "pull_request_target" in line:
            assert line.strip().startswith("#")
    assert "PRODUCTION_SCHEMA_AUDIT_DATABASE_URL" in workflow
    # Never reuse the admin/owner database credentials for the audit; the
    # owner-credential names may only appear in # comments forbidding them.
    active = [line for line in workflow.splitlines() if not line.strip().startswith("#")]
    non_secret = "\n".join(active).replace("PRODUCTION_SCHEMA_AUDIT_DATABASE_URL", "")
    assert "NEON_DIRECT_DATABASE_URL" not in non_secret
    assert "NEON_API_KEY" not in non_secret
    assert "DATABASE_URL" not in non_secret
    assert "permissions:" in workflow
    assert "contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "default_transaction_read_only" in workflow


@pytest.mark.skipif(
    shutil.which("docker") is None or shutil.which("pg_dump") is None,
    reason="requires docker and pg_dump for the throwaway round-trip",
)
def test_throwaway_postgres_round_trip_matches_and_detects_mutation() -> None:
    """A fixture-loaded throwaway DB matches; an added column/index fails."""
    container = "comic-pile-4735-audit"
    port = "5451"
    base = ["docker", "run", "-d", "--rm", "--name", container,
            "-e", "POSTGRES_PASSWORD=postgres", "-e", "POSTGRES_DB=postgres",
            "-p", f"127.0.0.1:{port}:5432", "postgres:16-alpine"]
    subprocess.run(["docker", "rm", "-f", container],
                   capture_output=True, check=False)
    try:
        started = subprocess.run(base, capture_output=True, text=True,
                                 timeout=120, check=False)
        assert started.returncode == 0, started.stderr
        import time

        for _ in range(60):
            ready = subprocess.run(
                ["docker", "exec", container, "pg_isready", "-h", "127.0.0.1",
                 "-U", "postgres"],
                capture_output=True, check=False, timeout=10,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            pytest.fail("throwaway postgres did not become ready")

        psql = ["docker", "exec", "-i", "-e", "PGPASSWORD=postgres", container,
                "psql", "-h", "127.0.0.1",
                "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1"]
        fixture = FIXTURE_PATH.read_bytes()
        loaded = subprocess.run(
            [*psql, "-q"],
            input=fixture, capture_output=True, check=False, timeout=120,
        )
        assert loaded.returncode == 0, loaded.stderr.decode("utf-8", "replace")

        dsn = f"postgresql://postgres:postgres@127.0.0.1:{port}/postgres"
        env = _child_env(_parse_dsn(dsn))
        dumped = subprocess.run(
            ["pg_dump", "--schema-only", "--no-owner", "--no-privileges",
             "--no-comments"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert dumped.returncode == 0, dumped.stderr
        matching = _compare_normalized_schemas(FIXTURE_TEXT, dumped.stdout)
        assert matching == {"added": [], "removed": [], "changed": []}

        subprocess.run(
            [*psql, "-c",
             "ALTER TABLE public.threads ADD COLUMN audit_probe integer;"],
            check=True, capture_output=True, timeout=60,
        )
        subprocess.run(
            [*psql, "-c",
             "CREATE INDEX ix_audit_probe ON public.threads (audit_probe);"],
            check=True, capture_output=True, timeout=60,
        )
        dumped_mutated = subprocess.run(
            ["pg_dump", "--schema-only", "--no-owner", "--no-privileges",
             "--no-comments"],
            env=env, capture_output=True, text=True, timeout=120,
        )
        assert dumped_mutated.returncode == 0, dumped_mutated.stderr
        drift = _compare_normalized_schemas(FIXTURE_TEXT, dumped_mutated.stdout)
        assert "TABLE threads" in drift["changed"]
        assert "INDEX ix_audit_probe" in drift["added"]
    finally:
        subprocess.run(["docker", "rm", "-f", container],
                       capture_output=True, check=False, timeout=60)


@pytest.mark.skipif(
    shutil.which("docker") is None or shutil.which("pg_dump") is None,
    reason="requires docker and pg_dump for the throwaway round-trip",
)
def test_documented_least_privilege_role_round_trip(tmp_path: Path) -> None:
    """The documented role setup makes the audit entry point pass then fail.

    Provisions ``schema_audit`` exactly as ``docs/PRODUCTION_SCHEMA_AUDIT.md``
    instructs (read-only role, bounded timeouts, SELECT-only grants), then runs
    ``scripts/production_schema_audit.py`` itself — not just the comparison
    helpers — against the fixture-loaded throwaway database: exit 0 on match,
    exit 1 with a bounded redacted diff on drift, exit 2 on the admin user,
    and no password in any output. This pins the documented production role
    contract and the least-privilege refusal to executable evidence.
    """
    import os
    import sys
    import time

    container = "comic-pile-4735-audit-role"
    port = "5452"
    password = "audit-role-test-pw-4735"
    base = ["docker", "run", "-d", "--rm", "--name", container,
            "-e", "POSTGRES_PASSWORD=postgres", "-e", "POSTGRES_DB=postgres",
            "-p", f"127.0.0.1:{port}:5432", "postgres:16-alpine"]
    subprocess.run(["docker", "rm", "-f", container],
                   capture_output=True, check=False)
    role_sql = f"""
CREATE ROLE schema_audit LOGIN PASSWORD '{password}' CONNECTION LIMIT 2;
ALTER ROLE schema_audit SET default_transaction_read_only = on;
ALTER ROLE schema_audit SET statement_timeout = '60s';
ALTER ROLE schema_audit SET lock_timeout = '30s';
GRANT CONNECT ON DATABASE postgres TO schema_audit;
GRANT USAGE ON SCHEMA public TO schema_audit;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO schema_audit;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO schema_audit;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO schema_audit;
"""
    psql_admin = ["docker", "exec", "-i", "-e", "PGPASSWORD=postgres", container,
                  "psql", "-h", "127.0.0.1",
                  "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1"]

    def run_audit(url_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.pop("PRODUCTION_SCHEMA_AUDIT_DATABASE_URL", None)
        env.update(url_env)
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts/production_schema_audit.py"),
             "--diff-output", str(tmp_path / "audit-diff.txt")],
            env=env, capture_output=True, text=True, timeout=180, check=False,
        )

    try:
        started = subprocess.run(base, capture_output=True, text=True,
                                 timeout=120, check=False)
        assert started.returncode == 0, started.stderr
        for _ in range(60):
            ready = subprocess.run(
                ["docker", "exec", container, "pg_isready", "-h", "127.0.0.1",
                 "-U", "postgres"],
                capture_output=True, check=False, timeout=10,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            pytest.fail("throwaway postgres did not become ready")

        fixture = FIXTURE_PATH.read_bytes()
        loaded = subprocess.run(
            [*psql_admin, "-q"],
            input=fixture, capture_output=True, check=False, timeout=120,
        )
        assert loaded.returncode == 0, loaded.stderr.decode("utf-8", "replace")
        provisioned = subprocess.run(
            psql_admin,
            input=role_sql.encode(), capture_output=True, check=False, timeout=60,
        )
        assert provisioned.returncode == 0, provisioned.stderr.decode(
            "utf-8", "replace")

        audit_dsn = (
            f"postgresql://schema_audit:{password}@127.0.0.1:{port}/postgres"
        )
        match = run_audit({"PRODUCTION_SCHEMA_AUDIT_DATABASE_URL": audit_dsn})
        assert match.returncode == 0, match.stdout + match.stderr
        assert "matches the canonical fixture" in match.stdout

        subprocess.run(
            [*psql_admin, "-c",
             "ALTER TABLE public.threads ADD COLUMN audit_probe integer;"],
            check=True, capture_output=True, timeout=60,
        )
        subprocess.run(
            [*psql_admin, "-c",
             "CREATE INDEX ix_audit_probe ON public.threads (audit_probe);"],
            check=True, capture_output=True, timeout=60,
        )
        drift = run_audit({"PRODUCTION_SCHEMA_AUDIT_DATABASE_URL": audit_dsn})
        assert drift.returncode == 1, drift.stdout + drift.stderr
        assert "changed: TABLE threads" in drift.stdout
        assert "added: INDEX ix_audit_probe" in drift.stdout
        diff_artifact = (tmp_path / "audit-diff.txt").read_text(encoding="utf-8")
        assert "ix_audit_probe" in diff_artifact
        assert password not in drift.stdout + drift.stderr + diff_artifact

        admin = run_audit(
            {"PRODUCTION_SCHEMA_AUDIT_DATABASE_URL":
             f"postgresql://postgres:postgres@127.0.0.1:{port}/postgres"}
        )
        assert admin.returncode == 2
        assert "refusing to run with an admin/owner database user" in admin.stderr

        missing = run_audit({})
        assert missing.returncode == 2
    finally:
        subprocess.run(["docker", "rm", "-f", container],
                       capture_output=True, check=False, timeout=60)
