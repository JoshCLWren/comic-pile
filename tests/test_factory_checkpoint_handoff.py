"""Regression coverage for deterministic recovery publication and safe retention."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "checkpoint_handoff", ROOT / ".github/scripts/factory_checkpoint_handoff.py",
)
assert SPEC and SPEC.loader
handoff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handoff)
REPO = "JoshCLWren/comic-pile"
RUN = "12345"
HEAD = "a" * 40
BASE = "b" * 40
BRANCH = f"factory/work-checkpoints/issue-4853/kilo-auto-free/{RUN}"


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> dict:
    state: dict = {
        "run": {"status": "completed", "html_url": f"https://github.com/{REPO}/actions/runs/{RUN}"},
        "saved": {"head": HEAD, "base": BASE, "tree": "c" * 40,
                  "branch": BRANCH, "mode": "pr", "number": 5152,
                  "worker": "46", "issue": "4853", "model": "kilo-auto/free"},
        "drafts": [], "calls": [], "comments": [], "incorporated": False,
    }
    monkeypatch.setattr(handoff, "verified_run", lambda *_: state["run"])
    monkeypatch.setattr(handoff, "checkpoint", lambda *_: state["saved"])
    monkeypatch.setattr(handoff, "recovery_prs", lambda *_: state["drafts"])
    monkeypatch.setattr(handoff, "incorporated", lambda *_: state["incorporated"])
    monkeypatch.setattr(handoff, "pages", lambda *_: state["comments"])

    def obj(endpoint: str) -> dict:
        if endpoint.endswith("/pulls/5200") and state["drafts"]:
            return state["drafts"][0]
        if "/pulls/" in endpoint:
            return {"number": 5152, "state": "open", "head": {
                "ref": "factory/98-4853-kilo-auto", "sha": "d" * 40,
                "repo": {"full_name": REPO}}, "merged": False}
        return {"number": 5152}

    def api(endpoint: str, method: str = "GET", **fields: object) -> object:
        state["calls"].append((endpoint, method, fields))
        if method == "POST" and endpoint.endswith("/pulls"):
            result = {"number": 5200, "state": "open", "draft": True, "labels": [],
                      "head": {"sha": HEAD}}
            state["drafts"].append(result)
            return result
        return None

    monkeypatch.setattr(handoff, "obj", obj)
    monkeypatch.setattr(handoff, "api", api)
    return state


def test_first_saved_repair_gets_linked_draft_without_mutating_original(harness: dict) -> None:
    result = handoff.publish(REPO, RUN)
    assert result["saved"] and result["published"] and not result["validated"]
    assert result["checkpoint_sha"] == HEAD
    create = next(call for call in harness["calls"] if call[0].endswith("/pulls"))
    assert create[2]["draft"] is True
    assert create[2]["head"] == BRANCH
    assert create[2]["base"] == "factory/98-4853-kilo-auto"
    assert "4853" in create[2]["body"] and "kilo-auto/free" in create[2]["body"]
    assert not any(call[0].endswith("/pulls/5152") for call in harness["calls"])
    assert not any(call[0].endswith("/issues/5152/labels") for call in harness["calls"])
    assert any(call[0].endswith("/issues/5152/comments") for call in harness["calls"])


def test_publication_retries_without_duplicate_pr_and_preserves_owner(harness: dict) -> None:
    handoff.publish(REPO, RUN)
    harness["drafts"][0]["labels"] = [{"name": "factory:local"}, {"name": "factory"}]
    harness["calls"].clear()
    handoff.publish(REPO, RUN)
    assert not any(call[0].endswith("/pulls") for call in harness["calls"])
    assert not any(call[0].endswith("/labels") for call in harness["calls"])
    assert any(call[0].endswith("/comments") for call in harness["calls"])



def test_existing_ready_recovery_keeps_its_state_and_accurate_link(harness: dict) -> None:
    """A manually published checkpoint must be reused without calling it a draft."""
    harness["drafts"] = [{"number": 5200, "state": "open", "draft": False,
                          "labels": [{"name": "factory"}, {"name": "factory:local"}]}]
    result = handoff.publish(REPO, RUN)
    assert result["published"] and result["recovery_pr"] == 5200
    assert not any(call[1] == "PATCH" or call[0].endswith("/pulls")
                   for call in harness["calls"])
    comments = [call[2]["body"] for call in harness["calls"]
                if call[0].endswith("/comments")]
    assert comments and "This recovery PR contains" in comments[0]
    assert "This draft" not in comments[0]

def test_issue_work_gets_main_draft(harness: dict) -> None:
    harness["saved"]["mode"] = "issue"
    handoff.publish(REPO, RUN)
    create = next(call for call in harness["calls"] if call[0].endswith("/pulls"))
    assert create[2]["base"] == "main"


def test_no_saved_diff_does_not_create_empty_pr(harness: dict) -> None:
    harness["saved"] = None
    assert handoff.publish(REPO, RUN) == {
        "saved": False, "published": False, "validated": False,
    }
    assert not harness["calls"]


def test_failed_work_is_retained_and_stays_unvalidated(harness: dict) -> None:
    harness["run"]["conclusion"] = "failure"
    result = handoff.publish(REPO, RUN, cleanup=True)
    assert result["saved"] and result["published"]
    assert result["validated"] is False
    assert not any(call[1] == "DELETE" for call in harness["calls"])


def test_incorporated_completed_work_closes_draft_then_deletes_only_saved_ref(harness: dict) -> None:
    handoff.publish(REPO, RUN)
    harness["calls"].clear()
    harness["incorporated"] = True
    result = handoff.publish(REPO, RUN, cleanup=True)
    assert result["retired"]
    assert any(call[1] == "PATCH" and call[2] == {"state": "closed"}
               for call in harness["calls"])
    deletes = [call[0] for call in harness["calls"] if call[1] == "DELETE"]
    assert deletes == [f"repos/{REPO}/git/refs/heads/{BRANCH}"]


@pytest.mark.parametrize("change", ["running", "owner", "ready", "hold"])
def test_live_or_owned_or_ready_work_cannot_be_cleaned(harness: dict, change: str) -> None:
    handoff.publish(REPO, RUN)
    harness["incorporated"] = True
    if change == "running":
        harness["run"]["status"] = "in_progress"
    elif change == "owner":
        harness["drafts"][0]["labels"] = [{"name": "factory:42"}]
    elif change == "ready":
        harness["drafts"][0]["draft"] = False
    else:
        harness["drafts"][0]["labels"] = [{"name": "do-not-merge"}]
    harness["calls"].clear()
    handoff.publish(REPO, RUN, cleanup=True)
    assert not any(call[1] in {"DELETE", "PATCH"} for call in harness["calls"])


def test_closed_draft_alone_is_not_permission_to_discard(harness: dict) -> None:
    harness["drafts"] = [{"number": 5200, "state": "closed", "draft": True}]
    result = handoff.publish(REPO, RUN, cleanup=True)
    assert result["saved"] and not result["published"]
    assert not any(call[1] == "DELETE" for call in harness["calls"])


def test_only_trusted_explicit_discard_retires_unincorporated_bytes(harness: dict) -> None:
    harness["drafts"] = [{"number": 5200, "state": "closed", "draft": True}]
    harness["comments"] = [{"body": "<!-- factory-checkpoint-discard:v1 -->",
                            "author_association": "NONE"}]
    handoff.publish(REPO, RUN, cleanup=True)
    assert not any(call[1] == "DELETE" for call in harness["calls"])
    harness["comments"][0]["author_association"] = "OWNER"
    result = handoff.publish(REPO, RUN, cleanup=True)
    assert result["retired"]


def test_incorporation_proves_additions_modes_and_deletions(monkeypatch: pytest.MonkeyPatch) -> None:
    base = {"old": ("old", "100644", "blob"), "edit": ("before", "100644", "blob")}
    saved = {"edit": ("after", "100755", "blob"), "new": ("new", "100644", "blob")}
    target = {**saved, "unrelated": ("other", "100644", "blob")}
    trees = {BASE: base, HEAD: saved, "d" * 40: target}
    monkeypatch.setattr(handoff, "tree", lambda _, sha: trees[sha])
    assert handoff.incorporated(REPO, {"base": BASE, "tree": HEAD}, "d" * 40)
    target["old"] = base["old"]
    assert not handoff.incorporated(REPO, {"base": BASE, "tree": HEAD}, "d" * 40)
    del target["old"]
    target["edit"] = ("after", "100644", "blob")
    assert not handoff.incorporated(REPO, {"base": BASE, "tree": HEAD}, "d" * 40)


@pytest.mark.parametrize("field,value", [
    ("path", ".github/workflows/untrusted.yml"),
    ("event", "pull_request"),
    ("head_branch", "arbitrary-pr-branch"),
    ("id", 98765),
    ("head_repository", {"full_name": "fork/repo"}),
])
def test_foreign_or_untrusted_runs_are_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object,
) -> None:
    run = {"path": handoff.WORKFLOW, "event": "workflow_dispatch",
           "id": int(RUN), "head_branch": "main",
           "repository": {"full_name": REPO}, "head_repository": {"full_name": REPO}}
    run[field] = value
    monkeypatch.setattr(handoff, "obj", lambda *_: run)
    with pytest.raises(ValueError, match="trusted"):
        handoff.verified_run(REPO, RUN)


def test_named_and_legacy_checkpoint_metadata_remain_recoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refs = [{"ref": f"refs/heads/{BRANCH}", "object": {"sha": HEAD}}]
    message = (f"checkpoint(factory): worker 46 run {RUN} pr #5152 (unreviewed recovery only)\n\n"
               f"Issue: 4853\nModel: kilo-auto/free\nBase-commit: {BASE}\n")
    monkeypatch.setattr(handoff, "pages", lambda *_: refs)
    monkeypatch.setattr(handoff, "obj", lambda path: (
        {"status": "ahead"} if "/compare/" in path else
        {"message": message, "tree": {"sha": "c" * 40}, "parents": [{"sha": BASE}]}
        if path.endswith(HEAD) else {"message": "base"}
    ))
    saved = handoff.checkpoint(REPO, RUN)
    assert saved["branch"] == BRANCH and saved["issue"] == "4853"
    refs[0]["ref"] = f"refs/heads/{handoff.PREFIX}{RUN}"
    message = message.split("\n\n")[0]
    saved = handoff.checkpoint(REPO, RUN)
    assert saved["base"] == BASE
    assert saved["branch"] == f"{handoff.PREFIX}{RUN}"


def test_workflow_and_entry_keep_recovery_independent_and_failure_visible() -> None:
    workflow = (ROOT / ".github/workflows/factory-checkpoint-reconcile.yml").read_text()
    assert "workflow_run:" in workflow and "schedule:" in workflow
    assert "ref: main" in workflow and "persist-credentials: false" in workflow
    assert "--cleanup" in workflow and "--sweep" in workflow
    entry = (ROOT / ".github/workflows/free-model-factory-entry.yml").read_text()
    assert "--outcome" in entry
    assert "Code saved to recovery; PR delivery incomplete; worker failed:" in entry
    assert 'if [[ "$verdict" == failed ]]; then' in entry


def test_failed_publication_still_records_saved_code_without_masking_failure(
    harness: dict, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    def broken(*_args: object, **_kwargs: object) -> dict:
        raise RuntimeError("transient GitHub failure")

    monkeypatch.setattr(handoff, "publish", broken)
    path = tmp_path / "outcome.json"
    path.write_text(json.dumps({"outcome_class": "work_failure", "delivery_outcome": "none"}))
    monkeypatch.setattr(sys, "argv", ["handoff", "--repo", REPO, "--run-id", RUN,
                                     "--outcome", str(path)])
    assert handoff.main() == 1
    result = json.loads(path.read_text())
    assert result["outcome_class"] == "work_failure" and result["delivery_outcome"] == "none"
    assert result["checkpoint_saved"] is True
    assert result["checkpoint_published"] is False
    assert result["checkpoint_validated"] is False
    assert result["checkpoint_sha"] == HEAD


def test_empty_sweep_is_a_successful_noop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(handoff, "pages", lambda *_: [])
    monkeypatch.setattr(sys, "argv", ["handoff", "--repo", REPO, "--sweep"])
    assert handoff.main() == 0
    assert json.loads(capsys.readouterr().out) == []
