"""Regression tests for factory issue implementation integrity (#4042)."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from pytest import MonkeyPatch

SCRIPTS = Path(__file__).resolve().parents[1] / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))

delivery = importlib.import_module("factory_implementation_delivery")
HEAD = "a" * 40
SOURCE = "app/services/reading_list_cycle_validator.py"
FRONT = "frontend/src/pages/CblBrowserPage.tsx"


def patch(path: str, old: list[str], new: list[str]) -> str:
    """Produce a per-file unified diff for a targeted regression.

    Args:
        path: Changed file path.
        old: Lines present before the change.
        new: Lines present after the change.

    Returns:
        A Git-style patch containing the supplied lines.
    """
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n+++ b/{path}\n"
        f"@@ -1,{len(old)} +1,{len(new)} @@\n"
        + "".join("-" + line + "\n" for line in old)
        + "".join("+" + line + "\n" for line in new)
    )


def test_docs_only_implementation_remains_open() -> None:
    """The #4040 docs-only PR cannot deliver CBL browser behavior."""
    docs = "docs/issue-plans/4010.md"
    ok, reason = delivery.pr_delivers_implementation(
        "Implement folder UI, navigation and source preview",
        [docs], patch(docs, ["Plan"], ["Revised plan"]),
    )
    assert not ok
    assert "production source" in reason


def test_docstring_only_implementation_remains_open() -> None:
    """The #4034 source docstring change must not qualify."""
    old = ['def validate():', '    """Old explanation', '    descriptive text."""',
           "    return False"]
    new = ['def validate():', '    """New explanation', '    different descriptive text."""',
           "    return False"]
    assert not delivery.pr_delivers_implementation(
        "Implement overlap-aware cycle validation", [SOURCE], patch(SOURCE, old, new)
    )[0]


def test_javascript_block_comment_is_not_code() -> None:
    """JS-style multiline comments are excluded."""
    old = ["/* Old", "   comment */", "export const ready = false;"]
    new = ["/* New", "   documentation only */", "export const ready = false;"]
    assert not delivery.pr_delivers_implementation(
        "Add new client behavior", [FRONT], patch(FRONT, old, new)
    )[0]


def test_docs_cannot_supply_evidence_for_comment_only_python() -> None:
    """A mixed docs/source diff must inspect only behavioral source."""
    docs = "docs/issue-plans/4017.md"
    diff = (
        patch(docs, ["Old prose"], ["New architecture guide"])
        + patch(SOURCE, ["# Old comment"], ["# New comment"])
    )
    assert not delivery.pr_delivers_implementation(
        "Implement new validator", [SOURCE, docs], diff
    )[0]


def test_deletion_only_fix_counts_as_behavior() -> None:
    """Removing a buggy early return is an implementation."""
    body = "Implement correct behavior by deleting early return"
    old = ["def validate():", "    return False", "    do_actual_work()"]
    new = ["def validate():", "    do_actual_work()"]
    assert delivery.pr_delivers_implementation(
        body, [SOURCE], patch(SOURCE, old, new)
    )[0]


def test_whitespace_only_change_not_delivery() -> None:
    """Reindentation without changed executable tokens is insufficient."""
    assert not delivery.pr_delivers_implementation(
        "Implement validation", [SOURCE],
        patch(SOURCE, ["    return False"], ["  return   False"]),
    )[0]


@pytest.mark.parametrize(
    "issue",
    [
        "Do not accept docs-only changes; implement the browser.",
        "Implement browser per PRD #123.",
        "Acceptance issue #900 was for planning. Implement this now.",
        "## Scope\n- Deliver executable behavior\n- No docs-only result.",
    ],
)
def test_incidental_doc_words_cannot_disable_gate(issue: str) -> None:
    """Mentioning documentation terms does not reclassify an issue."""
    assert delivery.is_implementation_issue(issue)


@pytest.mark.parametrize(
    "kind",
    ["docs-only", "documentation", "investigation", "prd", "acceptance-only"],
)
def test_explicit_docs_type_passes(kind: str) -> None:
    """Only a structured issue-type declaration allows non-code delivery."""
    assert not delivery.is_implementation_issue(
        f"**Issue type:** {kind}\n\nUpdate the requested document"
    )


def test_both_code_and_browser_test_pass_mechanical_gate() -> None:
    """Runnable implementation changes are not automatically rejected."""
    assert delivery.pr_delivers_implementation(
        "Implement CBL folder UI",
        [FRONT, "frontend/src/unit/CblBrowserPage.test.tsx"],
        patch(FRONT, ["return null;"], ["return <CBLBrowser />;"]),
    )[0]


def test_missing_diff_fails_closed() -> None:
    """Paths cannot be used as a proxy for executable code."""
    assert not delivery.pr_delivers_implementation(
        "Implement the search endpoint", [SOURCE]
    )[0]


def test_test_only_change_does_not_count_as_product_behavior() -> None:
    """A changed test does not by itself implement new product logic."""
    path = "tests/test_new_search.py"
    assert not delivery.pr_delivers_implementation(
        "Implement the search endpoint", [path],
        patch(path, ["assert False"], ["assert True"]),
    )[0]


def load_controller() -> ModuleType:
    """Load the production review controller as a testable module.

    Returns:
        Controller module with its real implementation policy wiring.
    """
    path = SCRIPTS / "factory-review-controller.py"
    spec = importlib.util.spec_from_file_location("factory_review_controller", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_authoritative_review_gate_rejects_docs_only_implementation(
    monkeypatch: MonkeyPatch,
) -> None:
    """The real controller gate, not just its helper, refuses docs-only PRs."""
    module = load_controller()
    doc = "docs/issue-plans/4010.md"
    commands: list[list[str]] = []
    current = {
        "state": "OPEN",
        "headRefName": "factory/44-4010-opencode-free",
        "headRefOid": HEAD,
    }
    monkeypatch.setattr(module, "pr_json", lambda _pr: current)
    monkeypatch.setattr(module, "target_json", lambda _n: {
        "state": "open", "body": "## Scope\n- Implement working CBL browser"
    })
    monkeypatch.setattr(module, "model_comment_bodies", lambda _pr: [])

    def fake_run(args: list[str], **_kwargs: object) -> SimpleNamespace:
        commands.append(args)
        text = doc + "\n" if "--name-only" in args else patch(
            doc, ["Plan"], ["Edited plan"]
        )
        return SimpleNamespace(stdout=text)

    monkeypatch.setattr(module, "run_gh", fake_run)
    verdict = module.issue_acceptance_gate(4040, HEAD)
    assert verdict["decision"] == "deny"
    assert "production source" in verdict["reason"]
    assert any("--patch" in command for command in commands)


def test_current_head_validation_rejects_racing_edits(
    monkeypatch: MonkeyPatch,
) -> None:
    """No stale-head executable evidence can be carried into approval."""
    module = load_controller()
    monkeypatch.setattr(module, "pr_json", lambda _pr: {"headRefOid": "b" * 40})
    monkeypatch.setattr(module, "run_gh", lambda args: SimpleNamespace(stdout=(
        SOURCE + "\n" if "--name-only" in args else
        patch(SOURCE, ["return False"], ["return True"])
    )))
    verdict = module.implementation_delivery_gate(44, HEAD, "Implement validation")
    assert verdict["decision"] == "retry"
    assert "changed" in verdict["reason"]


@pytest.mark.parametrize(
    "path,old,new",
    [
        ("Dockerfile", "RUN false", "RUN true"),
        ("Makefile", "build: old", "build: new"),
        (".github/workflows/ci.yml", "run: old", "run: new"),
        ("pyproject.toml", "requires-python = '>=3.11'",
         "requires-python = '>=3.14'"),
    ],
)
def test_build_and_workflow_fixes_are_code(
    path: str, old: str, new: str
) -> None:
    """Build and workflow edits can be valid executable deliverables."""
    assert delivery.pr_delivers_implementation(
        "Fix build and workflow behavior", [path],
        patch(path, [old], [new]),
    )[0]


@pytest.mark.parametrize(
    "old,new",
    [
        ('QUERY = """SELECT 1"""', 'QUERY = """SELECT 2"""'),
        ("QUERY = 'SELECT first column'", "QUERY = 'SELECT second column'"),
        ("message = 'hello world'", "message = 'hello  world'"),
    ],
)
def test_behavioral_string_value_edits_are_preserved(
    old: str, new: str
) -> None:
    """Meaningful string edits survive code token comparison."""
    assert delivery.pr_delivers_implementation(
        "Fix SQL query or message", [SOURCE],
        patch(SOURCE, [old], [new]),
    )[0]
