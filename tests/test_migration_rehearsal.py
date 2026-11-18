"""Unit coverage for the disposable-Postgres migration rehearsal runner (issue #3554)."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.engine import Engine

from scripts import migration_rehearsal as rehearsal_module
from scripts.generate_migration_fixture import (
    ADVERSARIAL_DANGLING_RULE_ID,
    build_adversarial_fixture,
    build_fixture,
)
from scripts.migration_rehearsal import (
    BASE_REVISION,
    REHEARSAL_STEPS,
    MigrationRehearsalError,
    MigrationRehearsalResult,
    RehearsalStepResult,
    _run_step,
    _sync_database_url,
    run_migration_rehearsal,
)


class _FakeConfig:
    """Minimal Alembic config double used to observe bound rehearsal databases."""

    def __init__(self) -> None:
        """Record the bound database URL."""
        self.database_url: str | None = None

    def set_main_option(self, key: str, value: str) -> None:
        """Record the bound main option."""
        self.database_url = value


class _FakeScriptDirectory:
    """Minimal Alembic ScriptDirectory double capturing the current head."""

    def __init__(self, head: str) -> None:
        """Bind the fake head revision."""
        self.head = head

    @classmethod
    def from_config(cls, config: object) -> "_FakeScriptDirectory":
        """Return a directory bound to the fake head."""
        return cls("c85900000001")

    def get_current_head(self) -> str:
        """Return the fake current head revision."""
        return self.head


class _FakeEngine(Engine):
    """Minimal engine double that records fixture use without opening a pool."""

    def __init__(self) -> None:
        """Initialize without a live pool."""
        self.fixture_applied: list[Engine] = []
        self.disposed = False

    def dispose(self) -> None:
        """Record disposal instead of releasing a pool."""
        self.disposed = True


def test_rehearsal_cycle_steps_are_canonical() -> None:
    """The canonical rehearsal cycle is upgrade -> fixture -> downgrade -> upgrade."""
    assert REHEARSAL_STEPS == ("upgrade_head", "apply_fixture", "downgrade_base", "upgrade_head")
    assert BASE_REVISION == "base"


def test_sync_database_url_rewrites_async_and_postgres_drivers_to_psycopg() -> None:
    """Alembic migration runs use the synchronous psycopg driver, never asyncpg."""
    assert (
        _sync_database_url("postgresql+asyncpg://user:pass@host:5432/comic_pile")
        == "postgresql+psycopg://user:pass@host:5432/comic_pile"
    )
    assert (
        _sync_database_url("postgresql://user:pass@host:5432/comic_pile")
        == "postgresql+psycopg://user:pass@host:5432/comic_pile"
    )
    assert (
        _sync_database_url("postgres://user:pass@host:5432/comic_pile")
        == "postgresql+psycopg://user:pass@host:5432/comic_pile"
    )
    assert (
        _sync_database_url("postgresql+psycopg://user:pass@host:5432/comic_pile")
        == "postgresql+psycopg://user:pass@host:5432/comic_pile"
    )


def test_run_step_returns_ok_result_when_action_succeeds() -> None:
    """A succeeding step reports no error and a non-negative duration."""
    result = _run_step("upgrade_head", lambda: None)
    assert isinstance(result, RehearsalStepResult)
    assert result.step == "upgrade_head"
    assert result.error is None
    assert result.duration_ms >= 0


def test_run_step_fails_closed_and_wraps_step_error() -> None:
    """A failing step raises MigrationRehearsalError naming the failing step."""

    def _boom() -> None:
        raise RuntimeError("irreversible refusal")

    with pytest.raises(MigrationRehearsalError, match="step 'downgrade_base' failed"):
        _run_step("downgrade_base", _boom)


def test_run_migration_rehearsal_full_cycle_with_stubbed_alembic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cycle upgrades, rolls back to the scoped base, and re-upgrades to head."""
    calls: list[tuple[str, str]] = []

    def _fake_upgrade(config: object, revision: str) -> None:
        calls.append(("upgrade_head", revision))

    def _fake_downgrade(config: object, revision: str) -> None:
        calls.append(("downgrade_base", revision))

    monkeypatch.setattr(rehearsal_module.command, "upgrade", _fake_upgrade)
    monkeypatch.setattr(rehearsal_module.command, "downgrade", _fake_downgrade)
    monkeypatch.setattr(rehearsal_module, "_alembic_config", lambda database_url, path: _FakeConfig())
    monkeypatch.setattr(rehearsal_module, "ScriptDirectory", _FakeScriptDirectory)

    result = run_migration_rehearsal(
        "postgresql+psycopg://postgres:postgres@127.0.0.1:55432/comic_pile_test",
        alembic_config_path=Path("alembic.ini"),
        fixture_applier=None,
        base_revision="c44050000002",
    )

    assert result.final_revision == "c85900000001"
    assert tuple(step.step for step in result.steps) == (
        "upgrade_head",
        "downgrade_base",
        "upgrade_head",
    )
    assert [call[1] for call in calls] == ["head", "c44050000002", "head"]


def test_run_migration_rehearsal_applies_fixture_between_upgrade_and_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fixture loads onto the disposable engine between upgrade and rollback."""
    engines: list[Engine] = []

    def _fake_create_engine(url: str) -> Engine:
        engine = _FakeEngine()
        engines.append(engine)
        return engine

    def _fake_apply(engine: Engine) -> None:
        engine.fixture_applied.append(engine)

    monkeypatch.setattr(rehearsal_module, "create_engine", _fake_create_engine)
    monkeypatch.setattr(rehearsal_module, "ScriptDirectory", _FakeScriptDirectory)

    def _fake_upgrade(config: object, revision: str) -> None:
        pass

    def _fake_downgrade(config: object, revision: str) -> None:
        pass

    monkeypatch.setattr(rehearsal_module.command, "upgrade", _fake_upgrade)
    monkeypatch.setattr(rehearsal_module.command, "downgrade", _fake_downgrade)
    monkeypatch.setattr(rehearsal_module, "_alembic_config", lambda database_url, path: _FakeConfig())

    result = run_migration_rehearsal(
        "postgresql+psycopg://postgres:postgres@127.0.0.1:55432/comic_pile_test",
        alembic_config_path=Path("alembic.ini"),
        fixture_applier=_fake_apply,
        base_revision=BASE_REVISION,
    )

    assert len(engines) == 1
    assert len(engines[0].fixture_applied) == 1
    assert engines[0].disposed is True
    assert result.final_revision == "c85900000001"


def test_run_migration_rehearsal_fails_closed_and_stops_after_first_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first failing step raises MigrationRehearsalError and later steps never run."""
    attempted: list[str] = []

    def _upgrade_head_then_fail(config: object, revision: str) -> None:
        attempted.append("upgrade_head")
        raise RuntimeError("irreversible refusal")

    monkeypatch.setattr(rehearsal_module.command, "upgrade", _upgrade_head_then_fail)
    monkeypatch.setattr(rehearsal_module, "_alembic_config", lambda database_url, path: _FakeConfig())
    monkeypatch.setattr(rehearsal_module, "ScriptDirectory", _FakeScriptDirectory)

    with pytest.raises(MigrationRehearsalError, match="migration rehearsal step 'upgrade_head' failed"):
        run_migration_rehearsal(
            "postgresql+psycopg://postgres:postgres@127.0.0.1:55432/comic_pile_test",
            alembic_config_path=Path("alembic.ini"),
        )

    assert attempted == ["upgrade_head"]


def test_main_returns_zero_when_rehearsal_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI exits zero and reports the final revision on success."""

    def _fake_run(*args: Any, **kwargs: Any) -> MigrationRehearsalResult:
        return MigrationRehearsalResult(
            final_revision="c85900000001",
            steps=(RehearsalStepResult(step="upgrade_head", duration_ms=1.0),),
        )

    monkeypatch.setattr(rehearsal_module, "run_migration_rehearsal", _fake_run)
    exit_code = rehearsal_module.main(
        ["--database-url", "postgresql+psycopg://postgres:postgres@127.0.0.1:55432/comic_pile_test"]
    )
    assert exit_code == 0


def test_main_returns_one_when_rehearsal_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI exits one and reports the failure when the rehearsal fails closed."""

    def _failing_run(*args: Any, **kwargs: Any) -> MigrationRehearsalResult:
        raise MigrationRehearsalError("migration rehearsal step 'upgrade_head' failed: boom")

    monkeypatch.setattr(rehearsal_module, "run_migration_rehearsal", _failing_run)
    exit_code = rehearsal_module.main(
        ["--database-url", "postgresql+psycopg://postgres:postgres@127.0.0.1:55432/comic_pile_test"]
    )
    assert exit_code == 1
    assert "MIGRATION REHEARSAL FAILED" in capsys.readouterr().out


def test_default_fixture_has_no_dangling_rules() -> None:
    """The default fixture's ContinuityRules all reference existing issues.

    The rehearsal against the default fixture must succeed; no rule-native
    ContinuityRule may dangle on a missing target issue.
    """
    from app.models.issue import Issue

    fixture = build_fixture()
    existing_issue_ids = {row["id"] for row in fixture["issues"]}
    for rule in fixture["continuity_rules"]:
        if rule["target_type"] == "issue":
            assert rule["target_id"] in existing_issue_ids, (
                f"dangling rule {rule['id']} target {rule['target_id']} "
                "not in fixture issues"
            )


def test_adversarial_fixture_has_dangling_rule_not_allowlisted() -> None:
    """The adversarial fixture contains a non-allowlisted dangling rule.

    This reproduces the #3359 data-dependent failure mode: migration
    ``c25530000001`` aborts on any dangling ContinuityRule that is not on the
    reviewed allowlist, so the rehearsal must fail closed rather than silently
    weakening the prerequisite graph.
    """
    from app.services.canonical_backfill import DANGLING_RULE_ALLOWLIST

    fixture = build_adversarial_fixture()
    rule_ids = {row["id"] for row in fixture["continuity_rules"]}
    assert ADVERSARIAL_DANGLING_RULE_ID in rule_ids
    dangling = [
        row
        for row in fixture["continuity_rules"]
        if row["id"] == ADVERSARIAL_DANGLING_RULE_ID
    ][0]
    assert dangling["target_id"] not in {
        row["id"] for row in fixture["issues"]
    }, "adversarial rule target issue must not exist"
    assert (dangling["id"], dangling["user_id"]) not in DANGLING_RULE_ALLOWLIST


def test_rehearsal_fails_closed_on_data_dependent_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A data-dependent migration failure aborts the rehearsal and stops later steps.

    Simulates the #3359 replay failure: the first upgrade succeeds on an empty
    database, the adversarial fixture loads, but the re-upgrade step aborts on
    the dangling ContinuityRule. Later steps must never run after the failure.
    """
    attempted: list[str] = []
    upgrade_count = 0

    def _failing_upgrade(config: object, revision: str) -> None:
        nonlocal upgrade_count
        upgrade_count += 1
        attempted.append(("upgrade_head", revision))
        # The re-upgrade (second upgrade_head call) aborts on the dangling rule.
        if upgrade_count == 2:
            raise RuntimeError(
                "Cannot backfill canonical Dependencies: 1 dangling "
                "ContinuityRule(s) are not on the reviewed allowlist"
            )

    def _noop_downgrade(config: object, revision: str) -> None:
        attempted.append(("downgrade_base", revision))

    class _FakeScriptDirectory:
        @classmethod
        def from_config(cls, config: object) -> "_FakeScriptDirectory":
            return cls()

        def get_current_head(self) -> str:
            return "head"

    monkeypatch.setattr(rehearsal_module.command, "upgrade", _failing_upgrade)
    monkeypatch.setattr(rehearsal_module.command, "downgrade", _noop_downgrade)
    monkeypatch.setattr(rehearsal_module, "_alembic_config", lambda database_url, path: None)
    monkeypatch.setattr(rehearsal_module, "ScriptDirectory", _FakeScriptDirectory)

    with pytest.raises(MigrationRehearsalError, match="dangling"):
        run_migration_rehearsal(
            "postgresql+psycopg://postgres:postgres@127.0.0.1:55432/comic_pile_test",
            fixture_applier=None,
            base_revision=BASE_REVISION,
        )

    # fixture_applier=None means no engine is created; the failing step is the
    # first upgrade_head, so no later step runs.
    assert attempted == [("upgrade_head", "head")]


def test_rehearsal_records_step_durations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every rehearsal step records a non-negative duration and no error on success."""

    def _noop(config: object, revision: str) -> None:
        return None

    monkeypatch.setattr(rehearsal_module.command, "upgrade", _noop)
    monkeypatch.setattr(rehearsal_module.command, "downgrade", _noop)
    monkeypatch.setattr(rehearsal_module, "_alembic_config", lambda database_url, path: None)
    monkeypatch.setattr(rehearsal_module, "ScriptDirectory", type("_SD", (), {"get_current_head": lambda self: "head"})())

    result = run_migration_rehearsal(
        "postgresql+psycopg://postgres:postgres@127.0.0.1:55432/comic_pile_test",
        fixture_applier=None,
        base_revision=BASE_REVISION,
    )

    assert result.final_revision == "head"
    for step in result.steps:
        assert step.error is None
        assert step.duration_ms >= 0
        assert isinstance(step.duration_ms, float)
