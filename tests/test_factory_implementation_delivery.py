"""Regression tests for factory issue implementation integrity (#4042)."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from pytest import MonkeyPatch

SCRIPTS = Path(__file__).resolve().parents[1] / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))

delivery = importlib.import_module("factory_implementation_delivery")
HEAD = "a" * 40
SOURCE = "app/services/reading_list_cycle_validator.py"
FRONT = "frontend/src/pages/CblBrowserPage.tsx"


def patch(path: str, old: list[str], new: list[str]) -> str:
    """Produce a per-file diff containing supplied lines and context.

    Args:
        path: Changed source path.
        old: Complete old source lines.
        new: Complete new source lines.

    Returns:
        Unified patch with the full file context.
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
    """Load the hyphenated production review controller.

    Returns:
        Imported production controller module.
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

    monkeypatch.setattr(module.implementation_delivery, "complete_pr_diff", lambda *_args: (
        [doc], patch(doc, ["Plan"], ["Edited plan"])
    ))
    verdict = module.issue_acceptance_gate(4040, HEAD)
    assert verdict["decision"] == "deny"
    assert "production source" in verdict["reason"]


def test_current_head_validation_rejects_racing_edits(
    monkeypatch: MonkeyPatch,
) -> None:
    """No stale-head executable evidence can be carried into approval."""
    module = load_controller()
    monkeypatch.setattr(module, "pr_json", lambda _pr: {"headRefOid": "b" * 40})
    monkeypatch.setattr(module.implementation_delivery, "complete_pr_diff", lambda *_args: (
        [SOURCE], patch(SOURCE, ["return False"], ["return True"])
    ))
    verdict = module.implementation_delivery_gate(44, HEAD, "Implement validation")
    assert verdict["decision"] == "retry"
    assert "changed" in verdict["reason"]


@pytest.mark.parametrize("path", ["Dockerfile", "Makefile", ".github/workflows/ci.yml"])
def test_behavioral_build_files_are_implementation(path: str) -> None:
    """Build and CI behavior must not require an unrelated application edit."""
    assert delivery.pr_delivers_implementation(
        "Repair the build", [path], patch(path, ["run: false"], ["run: true"])
    )[0]


@pytest.mark.parametrize("old,new", [
    ('QUERY = """SELECT 1"""', 'QUERY = """SELECT 2"""'),
    ('MESSAGE = "two words"', 'MESSAGE = "twowords"'),
    ('QUERY = """SELECT\n    1\n"""', 'QUERY = """SELECT\n    2\n"""'),
    ('URL = "https://a/#one"', 'URL = "https://a/#two"'),
])
def test_python_string_values_are_behavioral(old: str, new: str) -> None:
    """Literal contents, including spaces and comment markers, affect behavior."""
    assert delivery.pr_delivers_implementation(
        "Fix returned text", [SOURCE], patch(SOURCE, old.splitlines(), new.splitlines())
    )[0]


def test_long_docstring_and_block_comment_changes_are_not_behavior() -> None:
    """Complete-file context handles edits far from opening delimiters."""
    for path, opening, closing in ((SOURCE, '"""', '"""'), (FRONT, '/*', '*/')):
        old = [opening] + [f"explanation {i}" for i in range(30)] + [closing]
        new = old.copy()
        new[15] = "changed prose"
        assert not delivery.pr_delivers_implementation(
            "Implement browsing", [path], patch(path, old, new)
        )[0]


def test_complete_diff_uses_immutable_sources_and_preserves_no_newline() -> None:
    """The reader obtains whole files at merge base/head, including final lines."""
    import json

    calls: list[list[str]] = []

    def read(args: list[str]) -> str:
        calls.append(args)
        endpoint = args[-1]
        if endpoint.endswith("/pulls/44"):
            return json.dumps({"head": {"sha": HEAD}, "base": {"sha": "base"}})
        if "/compare/" in endpoint:
            return json.dumps({"merge_base_commit": {"sha": "ancestor"}})
        if endpoint.endswith("/files"):
            return json.dumps([[{"filename": SOURCE, "status": "modified",
                                 "patch": "@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2"}]])
        return "VALUE = 1" if endpoint.endswith("ref=ancestor") else "VALUE = 2"

    paths, diff = delivery.complete_pr_diff(44, HEAD, "owner/repo", read)
    assert delivery.pr_delivers_implementation("Fix value", paths, diff)[0]
    assert any(f"ref={HEAD}" in command[-1] for command in calls)


@pytest.mark.parametrize("closed", [False, True])
def test_post_merge_refuses_non_delivery_and_repairs_keyword_closure(
    monkeypatch: MonkeyPatch, closed: bool,
) -> None:
    """Both open issues and prematurely auto-closed issues retain implementation work."""
    closure = importlib.import_module("factory_post_merge_closure")

    monkeypatch.setattr(closure, "_pr_info", lambda _pr: {
        "branch": "factory/46-4042-kilo-auto", "body": "Closes #4042",
        "state": "MERGED", "head": HEAD,
    })
    monkeypatch.setattr(closure, "_issue_view", lambda _issue: {
        "state": "CLOSED" if closed else "OPEN", "body": "Implement browsing",
        "labels": ["factory", "ralph-status:done", "factory:unowned"],
    })
    monkeypatch.setattr(closure, "_issue_has_open_successor_pr", lambda *_args: False)
    monkeypatch.setattr(closure, "_repo_slug", lambda: "owner/repo")
    monkeypatch.setattr(closure, "_closed_by_pr", lambda *_args: True)
    monkeypatch.setattr(delivery, "complete_pr_diff", lambda *_args: (
        ["docs/plan.md"], patch("docs/plan.md", ["old"], ["new"])
    ))
    mutations: list[tuple[object, ...]] = []
    monkeypatch.setattr(closure, "_run_gh", lambda *args: mutations.append(args))
    monkeypatch.setattr(closure, "_replace_labels", lambda *args: mutations.append(args))
    monkeypatch.setattr(closure, "_comment_issue", lambda *args: mutations.append(args))
    monkeypatch.setattr(closure, "_close_issue", lambda *_args: pytest.fail("must not close"))
    assert closure.close_merged_pr_issue(4046).startswith("not-delivered:")
    assert bool(mutations) == closed
    if closed:
        assert any("reopen" in mutation for mutation in mutations)
        labels = mutations[0][1]
        assert isinstance(labels, list)
        assert "ralph-status:pending" in labels


@pytest.mark.parametrize("current,change,previous", [
    ("first\nlast", "@@ -2 +1,0 @@\n-removed", "first\nremoved\nlast"),
    ("", "@@ -1,2 +0,0 @@\n-first\n-second", "first\nsecond"),
    ("added", "@@ -0,0 +1 @@\n+added", ""),
])
def test_reverse_patch_handles_zero_length_sides(
    current: str, change: str, previous: str,
) -> None:
    """Added/deleted files and deletion-only hunks use Git's zero-count offsets."""
    assert delivery._previous_source(current, change) == previous


def test_truncated_source_patch_fails_closed() -> None:
    """GitHub's missing/truncated patch cannot become behavioral evidence."""
    with pytest.raises(RuntimeError, match="incomplete"):
        delivery._previous_source("new", "@@ -1,2 +1 @@\n-old\n+new")


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


@pytest.mark.parametrize("event,commit,expected", [
    ("closed", HEAD, True), ("closed", "other-delivery", False),
    ("closed", None, False), ("reopened", HEAD, False),
])
def test_only_own_keyword_closure_may_be_reopened(
    monkeypatch: MonkeyPatch, event: str, commit: str | None, expected: bool,
) -> None:
    """Historical non-delivery cannot undo a later delivery or manual closure."""
    import json

    closure = importlib.import_module("factory_post_merge_closure")
    monkeypatch.setattr(closure, "_repo_slug", lambda: "owner/repo")
    monkeypatch.setattr(closure, "_run_gh", lambda *_args: json.dumps([[
        {"event": "closed", "commit_id": HEAD}, {"event": event, "commit_id": commit},
    ]]))
    assert closure._closed_by_pr(4042, {"head": HEAD, "merge": "merge"}) is expected


@pytest.mark.parametrize("path", [".github/workflows/ci.yml", "Makefile"])
def test_indented_build_files_ignore_comment_lines_but_keep_structure(path: str) -> None:
    """Comment-only edits are excluded without losing significant indentation."""
    old = ["# old documentation", "build:", "  run: true"]
    new = ["build:", "  run: true"]
    assert not delivery.pr_delivers_implementation(
        "Fix build behavior", [path], patch(path, old, new)
    )[0]
    assert delivery.pr_delivers_implementation(
        "Fix build indentation", [path], patch(path, new, ["build:", "    run: true"])
    )[0]


@pytest.mark.parametrize("old,new", [
    ('if (( ${#prs[@]} > 1 )); then exit 1; fi',
     'if (( ${#prs[@]} > 2 )); then exit 1; fi'),
    ('echo ${value#prefix}', 'echo ${value#other}'),
    ('echo ${value:- #old}', 'echo ${value:- #new}'),
    ('echo ${value:-${other#old}}', 'echo ${value:-${other#new}}'),
    ('echo $#', 'echo $1'),
    ('echo foo#bar', 'echo foo#baz'),
    ('printf foo -bar', 'printf foo-bar'),
    ('echo first\necho second', 'echo first echo second'),
])
def test_shell_expansions_and_command_boundaries_are_behavioral(old: str, new: str) -> None:
    """Bash expansion hashes and word/command boundaries must survive comparison."""
    path = '.github/scripts/worker.sh'
    assert delivery.pr_delivers_implementation(
        "Fix shell behavior", [path], patch(path, old.splitlines(), new.splitlines())
    )[0]


@pytest.mark.parametrize("old,new", [
    ('# old comment\necho ok', '# new comment\necho ok'),
    ('echo ok # old', 'echo ok # new'),
    ('echo   ok', '  echo ok'),
    ('echo one; echo two', 'echo one\necho two'),
])
def test_shell_comments_and_formatting_do_not_qualify(old: str, new: str) -> None:
    """Comments and equivalent command formatting remain non-delivering."""
    path = '.github/scripts/worker.sh'
    assert not delivery.pr_delivers_implementation(
        "Fix shell behavior", [path], patch(path, old.splitlines(), new.splitlines())
    )[0]


@pytest.mark.parametrize("path,old,new", [
    ('frontend/src/styles.css', '.nav-item.active.nav-label { color: red; }',
     '.nav-item.active .nav-label { color: red; }'),
    ('frontend/src/client.ts', 'function f() { return value; }',
     'function f() { return\nvalue; }'),
    ('frontend/src/client.ts', 'let value = other;', 'let value = otherValue;'),
])
def test_language_significant_spacing_changes_qualify(path: str, old: str, new: str) -> None:
    """Selector descendants and JavaScript line terminators change behavior."""
    assert delivery.pr_delivers_implementation(
        "Fix behavior", [path], patch(path, old.splitlines(), new.splitlines())
    )[0]


@pytest.mark.parametrize("path,old,new", [
    ('frontend/src/styles.css', '.a { color: red; }', '.a{color:red;}'),
    ('frontend/src/styles.css', '.a { color : red; }', '.a{color:red;}'),
    ('frontend/src/client.ts', 'const value = 1;', 'const value=1;'),
    ('frontend/src/client.ts', 'function f() {\nreturn value;\n}',
     'function f(){return value;}'),
])
def test_ordinary_css_and_javascript_formatting_stays_non_delivery(
    path: str, old: str, new: str,
) -> None:
    """Spacing around punctuation and indentation alone does not deliver behavior."""
    assert not delivery.pr_delivers_implementation(
        "Fix behavior", [path], patch(path, old.splitlines(), new.splitlines())
    )[0]
