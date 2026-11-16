"""Contract tests for runtime model discovery after the roster removal (#5213).

The scheduled roster discovery workflow and its TSV were removed: workers
discover provider catalogs at execution time and real work establishes
callability. These tests keep that contract from regressing.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
FACTORY_RUN = WORKFLOWS / "free-model-factory-run.yml"


def test_no_scheduled_roster_discovery_workflow_exists() -> None:
    """Model discovery happens per execution, never by regenerating a roster."""
    assert not (WORKFLOWS / "factory-model-discovery.yml").exists()
    assert not (ROOT / ".github" / "free-model-factories.tsv").exists()
    for workflow in WORKFLOWS.glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        assert "factory/model-retirement" not in text, workflow.name
        assert "--dynamic-opencode-free" not in text, workflow.name


def test_runner_discovers_catalogs_at_execution_time() -> None:
    runner = FACTORY_RUN.read_text(encoding="utf-8")
    selector = runner.split("- name: Select execution candidate at dispatch time", 1)[1]
    selector = selector.split("- name:", 1)[0]
    assert "bash scripts/opencode-model-catalog.sh opencode verbose refresh" in selector
    assert "kilo models kilo-auto --refresh" in selector
    assert "factory_runtime_model_select.py" in selector
    assert "Nothing\n          # uses a checked-in model ID" in selector


def test_runner_uses_unpinned_opencode_v2() -> None:
    """The runner uses the current OpenCode 2 release, not repository pins."""
    runner = FACTORY_RUN.read_text(encoding="utf-8")
    installer = (ROOT / ".github" / "scripts" / "install-opencode-v2.sh").read_text(
        encoding="utf-8"
    )
    assert "npm view @opencode/cli versions --json" in installer
    assert '"@opencode/cli@$candidate"' in installer
    assert "No working published OpenCode v2 CLI" in installer
    assert "bash .github/scripts/install-opencode-v2.sh" in runner
    assert "OPENCODE_VERSION:" not in runner
    assert "OPENCODE_LINUX_X64_SHA256:" not in runner


def test_nvidia_410_evidence_comes_from_actual_assigned_work() -> None:
    """Sticky HTTP 410 evidence is only recorded from real NVIDIA work."""
    runner = FACTORY_RUN.read_text(encoding="utf-8")
    report = runner.split("      - name: Report terminal heartbeat", 1)[1]
    assert 'if [[ "$SOURCE" == nvidia && "$attempt_outcome" == model_retired_410 ]]' in report
    assert "retirement_marker='<!-- factory-model-retired-410:v1 -->'" in report
    assert "Confirmed HTTP 410 during actual assigned work" in report
