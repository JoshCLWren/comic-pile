from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONTROLLER_PATH = SCRIPT_DIR / "factory-review-controller.py"
VERDICT_PATH = SCRIPT_DIR / "factory-semantic-verdict.sh"
HEAD = "a" * 40
OLD_HEAD = "b" * 40


def load_controller():
    spec = importlib.util.spec_from_file_location("factory_review_controller", CONTROLLER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_required_checks_no_checks_configured_passes():
    controller = load_controller()
    result = controller.interpret_required_checks(
        [], command_status=1, stderr="no required checks reported for this branch"
    )
    assert result["decision"] == "pass"


def test_required_checks_pending_retries():
    controller = load_controller()
    result = controller.interpret_required_checks(
        [{"state": "PENDING"}], command_status=8, stderr=""
    )
    assert result["decision"] == "retry"


def test_required_checks_action_required_retries():
    controller = load_controller()
    result = controller.interpret_required_checks(
        [{"state": "ACTION_REQUIRED"}], command_status=1, stderr=""
    )
    assert result["decision"] == "retry"


def test_required_checks_failure_denies():
    controller = load_controller()
    result = controller.interpret_required_checks(
        [{"state": "FAILURE"}], command_status=1, stderr=""
    )
    assert result["decision"] == "deny"


def test_required_checks_all_passing_passes():
    controller = load_controller()
    result = controller.interpret_required_checks(
        [{"state": "SUCCESS"}, {"state": "SKIPPED"}, {"state": "NEUTRAL"}],
        command_status=0,
        stderr="",
    )
    assert result["decision"] == "pass"


def test_mergeable_unknown_then_mergeable(monkeypatch):
    controller = load_controller()
    states = iter(
        [
            {"state": "OPEN", "isDraft": False, "mergeable": "UNKNOWN", "headRefOid": HEAD},
            {"state": "OPEN", "isDraft": False, "mergeable": "MERGEABLE", "headRefOid": HEAD},
        ]
    )
    monkeypatch.setattr(controller, "pr_json", lambda _pr: next(states))
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)

    result = controller.poll_mergeable_gate(123, HEAD, poll_attempts=2, poll_interval=0)
    assert result["decision"] == "pass"


def test_stale_unresolved_thread_on_older_head_does_not_block():
    controller = load_controller()
    nodes = [
        {
            "isResolved": False,
            "comments": {
                "nodes": [{"commit": {"oid": OLD_HEAD}}],
                "pageInfo": {"hasNextPage": False},
            },
        }
    ]
    result = controller.interpret_review_threads(nodes, head=HEAD)
    assert result["decision"] == "pass"


def test_unresolved_thread_on_current_head_denies():
    controller = load_controller()
    nodes = [
        {
            "isResolved": False,
            "comments": {
                "nodes": [{"commit": {"oid": HEAD}}],
                "pageInfo": {"hasNextPage": False},
            },
        }
    ]
    result = controller.interpret_review_threads(nodes, head=HEAD)
    assert result["decision"] == "deny"


def bash_function(log_path: Path, expression: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            f"source {VERDICT_PATH!s}; {expression}",
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_verdict_marker_survives_trailing_output(tmp_path):
    log = tmp_path / "review.log"
    log.write_text(
        "Review complete. No blocking findings.\n"
        "FACTORY_GATE_READY\n"
        "Cost: $0.0042\n"
        "Tokens: 1842 input, 77 output\n"
    )
    result = bash_function(log, f"factory_extract_semantic_verdict {log}")
    assert result.returncode == 0
    assert result.stdout.strip() == "approve"


def test_marker_mentioned_in_prose_is_not_authoritative(tmp_path):
    log = tmp_path / "review.log"
    log.write_text("The protocol says to emit FACTORY_GATE_READY when appropriate.\nCost: $0.01\n")
    result = bash_function(log, f"factory_extract_semantic_verdict {log}")
    assert result.returncode != 0


def test_conflicting_exact_markers_still_detected_with_trailers(tmp_path):
    log = tmp_path / "review.log"
    log.write_text("FACTORY_GATE_READY\nFACTORY_GATE_BLOCKED\nTokens: 42\n")
    result = bash_function(log, f"factory_review_has_conflicting_terminal_markers {log}")
    assert result.returncode == 0


def test_terse_review_can_be_substantive_without_changed_path(tmp_path):
    log = tmp_path / "review.log"
    log.write_text(
        "Reviewed the behavior and exact-head constraints. The implementation preserves the trust boundary "
        "and I found no semantic blocker in the requested change."
    )
    result = bash_function(log, f"factory_review_is_substantive {log}")
    assert result.returncode == 0


def test_workflows_delegate_mechanical_gates_to_controller():
    root = SCRIPT_DIR.parent / "workflows"
    for name in ("factory-ready-merge-drain.yml", "fixed-model-factory-dispatch.yml"):
        text = (root / name).read_text()
        assert 'factory-review-controller.py' in text
        assert ' gates --pr ' in text
        assert 'gh pr checks' not in text
        assert 'reviewThreads(first:100)' not in text
        assert '--json state,isDraft,mergeable,headRefOid' not in text


def test_parse_checks_text_output_success():
    controller = load_controller()
    text = "ci/test\tsuccess\thttps://example.com\tSuccess\nbuild\tpending\thttps://example.com\tPending\n"
    checks = controller._parse_checks_text_output(text)
    assert len(checks) == 2
    assert checks[0]["name"] == "ci/test"
    assert checks[0]["conclusion"] == "Success"
    assert checks[1]["name"] == "build"
    assert checks[1]["conclusion"] == "Pending"


def test_parse_checks_text_output_empty():
    controller = load_controller()
    assert controller._parse_checks_text_output("") == []
    assert controller._parse_checks_text_output("  \n  ") == []


def test_parse_checks_text_output_single_column_skipped():
    controller = load_controller()
    text = "ci/test\tsuccess\thttps://example.com\n"
    checks = controller._parse_checks_text_output(text)
    assert len(checks) == 0


def test_conclusion_to_state_mapping():
    controller = load_controller()
    assert controller._conclusion_to_state("Success") == "SUCCESS"
    assert controller._conclusion_to_state("failure") == "FAILURE"
    assert controller._conclusion_to_state("skipped") == "SKIPPED"
    assert controller._conclusion_to_state("pending") == "PENDING"
    assert controller._conclusion_to_state("cancelled") == "CANCELLED"
    assert controller._conclusion_to_state("timed_out") == "TIMED_OUT"
    assert controller._conclusion_to_state("unknown_conclusion") == "UNKNOWN_CONCLUSION"


def test_required_checks_gate_json_fallback(monkeypatch):
    controller = load_controller()
    gh_calls = []

    def mock_run_gh(args, **kwargs):
        gh_calls.append(args)
        if "--json" in args:
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="unknown flag: --json\n",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="ci/test\tsuccess\thttps://example.com\tSuccess\n",
            stderr="",
        )

    monkeypatch.setattr(controller, "run_gh", mock_run_gh)
    result = controller.required_checks_gate(123)
    assert result["decision"] == "pass"
    assert len(gh_calls) == 2
    assert "--json" in gh_calls[0]
    assert "--json" not in gh_calls[1]


def test_required_checks_gate_json_fallback_no_checks(monkeypatch):
    controller = load_controller()

    def mock_run_gh(args, **kwargs):
        if "--json" in args:
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="unknown flag: --json\n",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="",
            stderr="no required checks reported for this branch\n",
        )

    monkeypatch.setattr(controller, "run_gh", mock_run_gh)
    result = controller.required_checks_gate(123)
    assert result["decision"] == "pass"
    assert "no required checks" in result["reason"]


def test_required_checks_gate_json_fallback_failure(monkeypatch):
    controller = load_controller()

    def mock_run_gh(args, **kwargs):
        if "--json" in args:
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="unknown flag: --json\n",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="ci/test\tcompleted\thttps://example.com\tFailure\nbuild\tcompleted\thttps://example.com\tSuccess\n",
            stderr="",
        )

    monkeypatch.setattr(controller, "run_gh", mock_run_gh)
    result = controller.required_checks_gate(123)
    assert result["decision"] == "deny"
    assert "FAILURE" in result["reason"]


def test_paused_schedule_blocks_remain_commented():
    root = SCRIPT_DIR.parent / "workflows"
    drain = (root / "factory-ready-merge-drain.yml").read_text()
    dispatcher = (root / "fixed-model-factory-dispatch.yml").read_text()
    assert "  # schedule:" in drain
    assert "  #   - cron: '2-57/5 * * * *'" in drain
    assert "  # schedule:" in dispatcher
    assert dispatcher.count("  #   - cron:") == 12
