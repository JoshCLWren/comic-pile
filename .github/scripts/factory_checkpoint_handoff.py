#!/usr/bin/env python3
"""Publish durable recovery drafts and retire only demonstrably incorporated snapshots.

This trusted-main controller reads GitHub objects as data. It never checks out or
executes checkpoint source, changes an assigned PR head, or grants review approval.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

PREFIX = "factory/work-checkpoints/"
SHA = re.compile(r"[a-f0-9]{40}")
META = re.compile(
    r"checkpoint\(factory\): worker ([1-9][0-9]*) run ([1-9][0-9]*) "
    r"(issue|pr) #([1-9][0-9]*) \(unreviewed recovery only\)"
)
WORKFLOW = ".github/workflows/free-model-factory-entry.yml"


def api(endpoint: str, method: str = "GET", **fields: object) -> object:
    """Make a bounded API request, preserving boolean JSON request values."""
    cmd = ["gh", "api", "--method", method, endpoint]
    payload = None
    if fields:
        cmd.extend(["--input", "-"])
        payload = json.dumps(fields)
    result = subprocess.run(cmd, input=payload, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError(f"GitHub {method} {endpoint}: {result.stderr[:300]}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def obj(endpoint: str) -> dict:
    """Require an object response rather than accepting truncated/malformed data."""
    value = api(endpoint)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected GitHub object: {endpoint}")
    return value


def pages(endpoint: str) -> list[dict]:
    """Read complete lists, failing closed at a bounded pagination limit."""
    result = []
    for page in range(1, 101):
        join = "&" if "?" in endpoint else "?"
        data = api(f"{endpoint}{join}per_page=100&page={page}")
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise RuntimeError(f"Expected GitHub list: {endpoint}")
        result.extend(data)
        if len(data) < 100:
            return result
    raise RuntimeError("Checkpoint pagination exceeded bound; no destructive action")


def verified_run(repo: str, run_id: str) -> dict:
    """Accept only this repository's canonical fixed-model worker runs."""
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise ValueError("Invalid factory run ID")
    run = obj(f"repos/{repo}/actions/runs/{run_id}")
    if (
        run.get("path", "").split("@", 1)[0] != WORKFLOW
        or run.get("repository", {}).get("full_name") != repo
        or run.get("head_repository", {}).get("full_name") != repo
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != "main"
        or str(run.get("id")) != run_id
    ):
        raise ValueError("Checkpoint does not belong to a trusted same-repository worker run")
    return run


def checkpoint(repo: str, run_id: str) -> dict | None:
    """Read the exact named remote ref and its complete checkpoint ancestry."""
    refs = pages(f"repos/{repo}/git/matching-refs/heads/{PREFIX}")
    refs = [ref for ref in refs if ref.get("ref") == f"refs/heads/{PREFIX}{run_id}"
            or ref.get("ref", "").endswith(f"/{run_id}")]
    if len(refs) > 1:
        raise ValueError("Ambiguous checkpoint refs for one run")
    if not refs:
        return None
    head = refs[0]["object"]["sha"]
    if not isinstance(head, str) or not SHA.fullmatch(head):
        raise ValueError("Invalid checkpoint SHA")
    tip = obj(f"repos/{repo}/git/commits/{head}")
    match = META.fullmatch(tip.get("message", "").splitlines()[0])
    if not match or match[2] != run_id:
        raise ValueError("Checkpoint identity does not match its run ref")
    metadata = dict(re.findall(r"(?m)^([A-Za-z-]+): (.+)$", tip.get("message", "")))
    common = {"head": head, "tree": tip["tree"]["sha"],
              "branch": refs[0]["ref"].removeprefix("refs/heads/"),
              "mode": match[3], "number": int(match[4]), "worker": match[1],
              "issue": metadata.get("Issue", ""), "model": metadata.get("Model", "")}
    base = metadata.get("Base-commit", "")
    if SHA.fullmatch(base):
        # New trusted writers record the initial base; verify it actually is
        # an ancestor before using it for a destructive incorporation proof.
        comparison = obj(f"repos/{repo}/compare/{base}...{head}")
        if comparison.get("status") not in {"ahead", "identical"}:
            raise ValueError("Checkpoint base is not an ancestor")
        return {**common, "base": base}
    cursor = tip
    for _ in range(200):
        parents = cursor.get("parents", [])
        if len(parents) != 1:
            raise ValueError("Checkpoint ancestry must be linear")
        parent = parents[0]["sha"]
        ancestor = obj(f"repos/{repo}/git/commits/{parent}")
        previous = META.fullmatch(ancestor.get("message", "").splitlines()[0])
        if not previous or previous.groups() != match.groups():
            return {**common, "base": parent}
        cursor = ancestor
    raise RuntimeError("Checkpoint ancestry exceeded bound; retaining branch")


def tree(repo: str, sha: str) -> dict[str, tuple[str, str, str]]:
    """Read all paths and modes; refuse GitHub's truncated recursive trees."""
    data = obj(f"repos/{repo}/git/trees/{sha}?recursive=1")
    if data.get("truncated") is not False:
        raise RuntimeError("Incomplete tree; retaining checkpoint")
    return {item["path"]: (item["sha"], item["mode"], item["type"])
            for item in data["tree"] if item["type"] != "tree"}


def incorporated(repo: str, saved: dict, destination: str) -> bool:
    """Prove every changed/deleted path's bytes and mode exist at destination."""
    base_tree = tree(repo, saved["base"])
    saved_tree = tree(repo, saved["tree"])
    target_tree = tree(repo, destination)
    changed = {path for path in base_tree.keys() | saved_tree.keys()
               if base_tree.get(path) != saved_tree.get(path)}
    return bool(changed) and all(target_tree.get(path) == saved_tree.get(path) for path in changed)


def recovery_prs(repo: str, branch_name: str) -> list[dict]:
    """Find draft handoff PRs by the exact same-repository head branch."""
    owner = repo.split("/", 1)[0]
    branch = quote(f"{owner}:{branch_name}", safe="")
    return pages(f"repos/{repo}/pulls?state=all&head={branch}")


def marker(run_id: str) -> str:
    """Return the idempotency marker for links and metadata."""
    return f"<!-- factory-checkpoint-handoff:v1 run={run_id} -->"


def link(repo: str, number: int, run_id: str, draft: int) -> None:
    """Attach a recovery draft without changing the original target's lease."""
    comments = pages(f"repos/{repo}/issues/{number}/comments")
    if any(marker(run_id) in comment.get("body", "") for comment in comments):
        return
    api(f"repos/{repo}/issues/{number}/comments", "POST", body=(
        f"{marker(run_id)}\nSaved recovery work: #{draft}. "
        "This draft contains unvalidated snapshots, does not approve or replace this target, "
        "and preserves its current owner."
    ))


def publish(repo: str, run_id: str, *, cleanup: bool = False) -> dict:
    """Ensure every saved attempt has a draft PR, optionally retiring proven work."""
    run = verified_run(repo, run_id)
    saved = checkpoint(repo, run_id)
    if saved is None:
        return {"saved": False, "published": False, "validated": False}
    drafts = recovery_prs(repo, saved["branch"])
    open_prs = [pr for pr in drafts if pr.get("state") == "open"]
    if len(open_prs) > 1:
        raise RuntimeError("Multiple recovery PRs for one run; retaining all work")
    target = obj(f"repos/{repo}/issues/{saved['number']}")
    original = None
    if saved["mode"] == "pr":
        original = obj(f"repos/{repo}/pulls/{saved['number']}")
        if original.get("head", {}).get("repo", {}).get("full_name") != repo:
            raise ValueError("Recovery must not target a fork")
    # Never infer incorporation from 'some PR was updated'. Compare every saved
    # changed blob/mode/deletion against the actual destination at this instant.
    destination = original
    if destination is None:
        destination = recorded_delivery(repo, drafts, saved["head"])
    if cleanup and run.get("status") == "completed" and explicitly_discarded(repo, drafts):
        return retire(repo, run_id, saved, drafts, "explicitly discarded by trusted operator")
    if cleanup and run.get("status") == "completed" and destination:
        sha = destination.get("merge_commit_sha") if destination.get("merged") else None
        sha = sha or destination.get("head", {}).get("sha")
        if SHA.fullmatch(str(sha)) and incorporated(repo, saved, sha):
            return retire(repo, run_id, saved, drafts, sha)
    if open_prs:
        draft = open_prs[0]
    elif drafts:
        # A closed recovery draft is an explicit human-visible state, not
        # permission to throw away bytes or repeatedly reopen a declined PR.
        return {"saved": True, "published": False, "validated": False,
                "checkpoint_sha": saved["head"], "recovery_pr": drafts[0]["number"],
                "detail": "closed recovery retained; incorporation not proven"}
    else:
        # Repairs target the original branch while it exists. If it has been
        # deleted, keep recovery discoverable against main with clear linkage.
        base = original["head"]["ref"] if original and original.get("state") == "open" else "main"
        body = (f"{marker(run_id)}\n\nRecovery snapshots for {saved['mode']} "
                f"#{saved['number']} from [worker run]({run['html_url']}).\n\n"
                f"Original issue: {saved['issue'] or 'not recorded (legacy checkpoint)'}.\n"
                f"Model: `{saved['model'] or 'not recorded (legacy checkpoint)'}`.\n\n"
                "Owner objective: preserve and expose interrupted factory work.\n"
                "This PR delivers: durable, unreviewed recovery snapshots.\n"
                "Still missing: local validation and independent review before delivery.\n"
                "Safety/rollout basis: owner-authorized recovery draft; original target lease preserved.\n"
                "Validation: unvalidated; saving or publishing is not approval.\n")
        result = api(f"repos/{repo}/pulls", "POST",
                     title=f"Recovery: {saved['mode']} #{saved['number']} (run {run_id})",
                     head=saved["branch"], base=base, body=body, draft=True)
        if not isinstance(result, dict):
            raise RuntimeError("GitHub did not return a recovery PR")
        draft = result
    # Also retry these operations when the ref/tree is unchanged; publication
    # can succeed before labels/linking fail or a response is lost.
    if not any(label.get("name", "").startswith("factory") for label in draft.get("labels", [])):
        api(f"repos/{repo}/issues/{draft['number']}/labels", "POST",
            labels=["factory", "factory:building", "factory:unowned"])
    link(repo, target["number"], run_id, draft["number"])
    return {"saved": True, "published": True, "validated": False,
            "checkpoint_sha": saved["head"], "recovery_pr": draft["number"],
            "checkpoint_branch": saved["branch"]}


def retire(repo: str, run_id: str, saved: dict, drafts: list[dict], destination: str) -> dict:
    """Close superseded drafts and delete only an unchanged, incorporated ref."""
    # Re-read immediately before mutation. A moved ref or running model is
    # retained rather than risking a concurrent checkpoint writer's next bytes.
    run = verified_run(repo, run_id)
    current = checkpoint(repo, run_id)
    if run.get("status") != "completed" or not current or current["head"] != saved["head"]:
        return {"saved": True, "published": bool(drafts), "validated": False,
                "detail": "live or moved checkpoint retained"}
    drafts = [obj(f"repos/{repo}/pulls/{draft['number']}") for draft in drafts]
    for draft in drafts:
        labels = {label.get("name", "") for label in draft.get("labels", [])}
        if draft.get("state") == "open" and (
            draft.get("draft") is not True
            or draft.get("head", {}).get("sha") != saved["head"]
            or any(re.fullmatch(r"factory:(local|[1-9][0-9]*)", label) for label in labels)
            or labels & {"factory:blocked", "needs-human", "do-not-merge", "security-review"}
        ):
            return {"saved": True, "published": True, "validated": False,
                    "detail": "recovery PR has live ownership, hold, or review state; retained"}
    for draft in drafts:
        if draft.get("state") == "open":
            api(f"repos/{repo}/issues/{draft['number']}/comments", "POST", body=(
                f"All saved changed paths match destination `{destination}`. "
                "Closing superseded recovery draft; this does not grant review approval."
            ))
            api(f"repos/{repo}/pulls/{draft['number']}", "PATCH", state="closed")
    api(f"repos/{repo}/git/refs/heads/{quote(saved['branch'], safe='/')}", "DELETE")
    return {"saved": True, "published": bool(drafts), "validated": False,
            "retired": True, "incorporated_at": destination}


def explicitly_discarded(repo: str, drafts: list[dict]) -> bool:
    """Require a closed draft plus an explicit trusted operator discard marker."""
    for draft in drafts:
        if draft.get("state") != "closed" or draft.get("merged_at"):
            continue
        for comment in pages(f"repos/{repo}/issues/{draft['number']}/comments"):
            if (comment.get("author_association") in {"OWNER", "MEMBER", "COLLABORATOR"}
                    and "<!-- factory-checkpoint-discard:v1 -->" in comment.get("body", "")):
                return True
    return False


def recorded_delivery(repo: str, drafts: list[dict], checkpoint_sha: str) -> dict | None:
    """Read only trusted wrapper delivery records, never model-authored prose."""
    for draft in drafts:
        for comment in pages(f"repos/{repo}/issues/{draft['number']}/comments"):
            trusted = comment.get("author_association") in {"OWNER", "MEMBER", "COLLABORATOR"}
            trusted = trusted or comment.get("user", {}).get("login") == "github-actions[bot]"
            found = re.search(
                r"<!-- factory-checkpoint-delivery:v1 pr=([1-9][0-9]*) "
                r"checkpoint=([a-f0-9]{40}) -->", comment.get("body", ""))
            if trusted and found and found[2] == checkpoint_sha:
                destination = obj(f"repos/{repo}/pulls/{found[1]}")
                if destination.get("head", {}).get("repo", {}).get("full_name") == repo:
                    return destination
    return None


def record_delivery(repo: str, run_id: str, saved: dict, delivered_pr: int) -> dict:
    """Persist a verified destination now; completed-run cleanup may retire it later."""
    destination = obj(f"repos/{repo}/pulls/{delivered_pr}")
    head = destination.get("head", {})
    if head.get("repo", {}).get("full_name") != repo or not incorporated(repo, saved, head["sha"]):
        return {"saved": True, "published": False, "validated": False,
                "detail": "delivery does not contain all saved bytes; retained"}
    drafts = recovery_prs(repo, saved["branch"])
    for draft in drafts:
        delivery_marker = (f"<!-- factory-checkpoint-delivery:v1 pr={delivered_pr} "
                           f"checkpoint={saved['head']} -->")
        comments = pages(f"repos/{repo}/issues/{draft['number']}/comments")
        if not any(delivery_marker in comment.get("body", "") for comment in comments):
            api(f"repos/{repo}/issues/{draft['number']}/comments", "POST",
                body=f"{delivery_marker}\nSaved bytes incorporated in #{delivered_pr}; cleanup after worker termination.")
    return retire(repo, run_id, saved, drafts, head["sha"])


def enrich_outcome(path: Path, result: dict) -> None:
    """Add verified recovery facts without rewriting the agent outcome class."""
    outcome = json.loads(path.read_text())
    outcome["checkpoint_saved"] = result.get("saved", False)
    outcome["checkpoint_published"] = result.get("published", False)
    outcome["checkpoint_validated"] = False
    outcome["recovery_pr"] = result.get("recovery_pr", "")
    outcome["checkpoint_sha"] = result.get("checkpoint_sha", "")
    path.write_text(json.dumps(outcome) + "\n")


def main() -> int:
    """Run one publish, completion reconciliation, or bounded scheduled sweep."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--outcome", type=Path)
    parser.add_argument("--delivered-pr", type=int)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("Invalid repository")
    ids = [args.run_id] if args.run_id else []
    if args.sweep:
        refs = pages(f"repos/{args.repo}/git/matching-refs/heads/{PREFIX}")
        ids = sorted({ref["ref"].rsplit("/", 1)[-1] for ref in refs})
    if not ids and not args.sweep:
        parser.error("--run-id or --sweep is required")
    results = []
    failed = False
    for run_id in ids:
        try:
            result = publish(args.repo, run_id, cleanup=args.cleanup)
            if args.delivered_pr and result.get("saved"):
                saved = checkpoint(args.repo, run_id)
                if saved:
                    result = record_delivery(args.repo, run_id, saved, args.delivered_pr)
            result["run_id"] = run_id
            results.append(result)
            if args.outcome:
                enrich_outcome(args.outcome, result)
        except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
            failed = True
            result = {"run_id": run_id, "error": str(error)}
            if args.outcome:
                # Publication failure must not erase independently verified
                # remote persistence, nor change the worker's failing class.
                try:
                    saved = checkpoint(args.repo, run_id)
                    result["saved"] = bool(saved)
                    if saved:
                        result["checkpoint_sha"] = saved["head"]
                    enrich_outcome(args.outcome, result)
                except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired):
                    pass  # Independent reconciliation retries; never invent proof.
            results.append(result)
    print(json.dumps(results, indent=2))
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
