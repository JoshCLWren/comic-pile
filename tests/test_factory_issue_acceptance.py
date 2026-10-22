"""Regression tests for exact-head issue-contract verification (#4045)."""

import importlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))
acceptance = importlib.import_module("factory_issue_acceptance")
HEAD = "a" * 40
NEXT = "b" * 40
ISSUE = "## Scope\n- Render folders and pagination\n- Show source preview\n\n## Acceptance tests\n- Browser test proves navigation\n"
FILE = "frontend/src/pages/CblBrowserPage.tsx"


def complete_report():
    return {
        "issue": 4010,
        "head": HEAD,
        "items": [
            {
                "id": f"A{i}",
                "status": "pass",
                "file": FILE,
                "evidence": "Verified the actual browser and source preview implementation in this changed file.",
                "test": "pnpm playwright test cbl-browser.spec.ts passed",
            }
            for i in range(1, 4)
        ],
    }


def errors(report=None, body=ISSUE, head=HEAD, paths=(FILE,)):
    return acceptance.validate(
        complete_report() if report is None else report, 4010, head, body, paths
    )


def test_complete_issue_requirements_pass():
    assert len(acceptance.requirements(ISSUE)) == 3
    assert errors() == []


def test_missing_criterion_blocks_approval():
    report = complete_report()
    report["items"].pop()
    assert "cover all 3" in " ".join(errors(report))


def test_false_pass_without_actual_changed_file_blocks():
    report = complete_report()
    report["items"][0]["file"] = "docs/issue-plans/4010.md"
    assert "cite a file changed" in " ".join(errors(report))


def test_generic_claim_without_test_or_evidence_blocks():
    report = complete_report()
    report["items"][0]["evidence"] = "done"
    report["items"][0]["test"] = "tests passed"
    assert len(errors(report)) == 2


def test_malformed_or_duplicate_report_fails_closed():
    report = complete_report()
    report["items"][1]["id"] = "A1"
    assert errors(report)
    assert acceptance.report_from_text("FACTORY_GATE_READY") is None
    assert acceptance.report_from_text("FACTORY_ACCEPTANCE_V1=not-json") is None


def test_contract_head_and_issue_must_match():
    assert errors(head=NEXT)
    assert errors(body=ISSUE + "\n- another requirement")


def test_issue_body_revision_and_head_invalidate_trusted_marker():
    old = acceptance.marker(4010, HEAD, ISSUE)
    assert acceptance.attested([f"{old}\n### Review"], 4010, HEAD, ISSUE)
    assert not acceptance.attested([old], 4010, NEXT, ISSUE)
    assert not acceptance.attested([old], 4010, HEAD, ISSUE + "\nNew requirement")
    assert not acceptance.attested(["<!-- untrusted imitation -->"], 4010, HEAD, ISSUE)


def test_doc_only_issue_is_not_forced_to_change_executable_files():
    issue = "## Scope\n- Correct the contributor guide\n"
    report = {
        "issue": 4010, "head": HEAD, "items": [
            {"id": "A1", "status": "pass", "file": "docs/guide.md",
             "evidence": "Updated actual instructions, verified link and command names by inspection.",
             "test": "manual docs inspection: all examples checked"}
        ],
    }
    assert errors(report, body=issue, paths=("docs/guide.md",)) == []


def test_docstring_only_pr_cannot_claim_unmodified_executable_code():
    report = complete_report()
    report["items"][0]["file"] = "app/services/reading_list_cycle_validator.py"
    # A separate #4042 mechanical-diff gate rejects a docstring-only change.
    # Here it is also impossible to claim the browser implementation from
    # a changed file that does not implement any browser behavior.
    assert errors(report, paths=("app/services/reading_list_cycle_validator.py",))


def test_report_line_is_structured_and_exact():
    import json
    report = complete_report()
    line = acceptance.PREFIX + json.dumps(report)
    assert acceptance.report_from_text("Read issue and diff\n" + line + "\nFACTORY_GATE_READY") == report
    assert acceptance.report_from_text(line + "\n" + line) is None
