#!/usr/bin/env python3
"""Turn persisted Chromium discovery failures into deduplicated factory issues."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FAILED_RESULT_STATUSES = {"failed", "timedOut", "interrupted"}
PRODUCT_LABELS = (
    "bug",
    "e2e-discovered",
    "factory",
    "factory:unowned",
    "ralph-task",
    "ralph-status:pending",
)
INFRA_LABELS = (
    "e2e-infrastructure",
    "factory",
    "factory:unowned",
    "ralph-task",
    "ralph-status:pending",
)


@dataclass(frozen=True)
class Failure:
    """One unexpected Playwright test outcome from a persisted JSON report."""

    file: str
    title: str
    project: str
    message: str
    artifact: str

    @property
    def fingerprint(self) -> str:
        """Return a stable identity for cross-run issue deduplication."""
        payload = f"{self.file}\n{self.title}\n{self.project}".encode()
        return hashlib.sha256(payload).hexdigest()[:16]


def run_gh(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run GitHub CLI with captured text output."""
    return subprocess.run(
        ["gh", *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def ensure_labels() -> None:
    """Ensure discovery-specific labels exist before issue creation."""
    run_gh(
        "label",
        "create",
        "e2e-discovered",
        "--color",
        "1D76DB",
        "--description",
        "Reproducible product failure discovered by scheduled Chromium E2E",
        "--force",
    )
    run_gh(
        "label",
        "create",
        "e2e-infrastructure",
        "--color",
        "FBCA04",
        "--description",
        "Chromium discovery infrastructure failed before product evidence was produced",
        "--force",
    )


def find_artifact_root(path: Path, boundary: Path) -> Path:
    """Find the downloaded artifact directory containing one results file."""
    current = path.parent
    while current != boundary and boundary in current.parents:
        if (current / "discovery-artifacts").exists():
            return current
        current = current.parent
    return path.parent


def failure_message(test: dict[str, Any]) -> str:
    """Return the most useful bounded error text from the final failed attempt."""
    results = test.get("results") or []
    for result in reversed(results):
        if result.get("status") not in FAILED_RESULT_STATUSES:
            continue
        error = result.get("error") or {}
        text = error.get("message") or error.get("stack") or ""
        if not text:
            errors = result.get("errors") or []
            text = "\n".join(
                str(item.get("message") or item.get("stack") or item)
                for item in errors
            )
        if text:
            return str(text)[:6000]
    return "Playwright reported an unexpected test outcome without a structured error message."


def collect_suite_failures(
    suite: dict[str, Any],
    artifact: str,
    ancestors: tuple[str, ...] = (),
) -> list[Failure]:
    """Recursively collect tests whose final Playwright status is unexpected."""
    suite_title = str(suite.get("title") or "").strip()
    titles = (*ancestors, suite_title) if suite_title else ancestors
    failures: list[Failure] = []

    for spec in suite.get("specs") or []:
        spec_title = str(spec.get("title") or "Unnamed Chromium test").strip()
        file_name = str(spec.get("file") or suite.get("file") or "unknown-spec")
        full_title = " › ".join((*titles, spec_title))
        for test in spec.get("tests") or []:
            results = test.get("results") or []
            final_status = results[-1].get("status") if results else None
            test_status = test.get("status")
            if test_status != "unexpected" and not (
                test_status is None and final_status in FAILED_RESULT_STATUSES
            ):
                continue
            failures.append(
                Failure(
                    file=file_name,
                    title=full_title,
                    project=str(test.get("projectName") or "chromium"),
                    message=failure_message(test),
                    artifact=artifact,
                )
            )

    for child in suite.get("suites") or []:
        failures.extend(collect_suite_failures(child, artifact, titles))
    return failures


def collect_failures(root: Path) -> tuple[list[Failure], list[str]]:
    """Collect product failures and artifacts that never produced JSON results."""
    failures: list[Failure] = []
    artifacts_with_results: set[Path] = set()

    for result_file in root.rglob("results.json"):
        artifact_root = find_artifact_root(result_file, root)
        artifacts_with_results.add(artifact_root)
        try:
            payload = json.loads(result_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"warning: could not parse {result_file}: {exc}")
            continue
        artifact = artifact_root.name
        for suite in payload.get("suites") or []:
            failures.extend(collect_suite_failures(suite, artifact))

    missing_results: list[str] = []
    for metadata_file in root.rglob("run-metadata.json"):
        artifact_root = metadata_file.parent.parent
        if artifact_root in artifacts_with_results:
            continue
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            metadata = {}
        if metadata.get("job_status") == "success":
            continue
        missing_results.append(artifact_root.name)

    return failures, sorted(set(missing_results))


def open_issue_markers() -> dict[str, int]:
    """Return existing open discovery marker to issue-number mappings."""
    payload = run_gh(
        "issue",
        "list",
        "--state",
        "open",
        "--limit",
        "500",
        "--json",
        "number,body",
    ).stdout
    issues = json.loads(payload or "[]")
    markers: dict[str, int] = {}
    prefix = "<!-- chromium-discovery-failure:"
    for issue in issues:
        body = issue.get("body") or ""
        start = body.find(prefix)
        if start < 0:
            continue
        end = body.find(" -->", start)
        if end < 0:
            continue
        marker = body[start : end + 4]
        markers[marker] = int(issue["number"])
    return markers


def evidence_header(artifact: str) -> str:
    """Build durable run evidence shared by new issues and repeat comments."""
    repository = os.environ["GITHUB_REPOSITORY"]
    run_id = os.environ["GITHUB_RUN_ID"]
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    sha = os.environ["GITHUB_SHA"]
    return (
        f"Run: https://github.com/{repository}/actions/runs/{run_id}\n"
        f"Artifact: `{artifact}`\n"
        f"Run attempt: `{attempt}`\n"
        f"Commit: `{sha}`"
    )


def create_or_update_product_issue(failure: Failure, markers: dict[str, int]) -> None:
    """Create one issue per stable failing test or append fresh run evidence."""
    marker = f"<!-- chromium-discovery-failure:{failure.fingerprint} -->"
    evidence = evidence_header(failure.artifact)
    details = (
        f"{evidence}\n\n"
        f"Spec: `{failure.file}`\n"
        f"Project: `{failure.project}`\n"
        f"Test: {failure.title}\n\n"
        "Failure:\n```text\n"
        f"{failure.message}\n"
        "```"
    )
    existing = markers.get(marker)
    if existing is not None:
        run_gh("issue", "comment", str(existing), "--body", f"Fresh Chromium failure evidence:\n\n{details}")
        print(f"updated existing E2E issue #{existing}: {failure.title}")
        return

    title_tail = failure.title.split(" › ")[-1]
    title = f"E2E: {title_tail}"[:240]
    body = (
        f"{marker}\n\n"
        "Scheduled Chromium discovery reproduced a product-facing failure after Playwright retries. "
        "Treat this as normal executable factory work. Diagnose the product behavior, fix it, and keep "
        "or strengthen the focused regression coverage that proves the corrected behavior.\n\n"
        f"{details}"
    )
    args = ["issue", "create", "--title", title, "--body", body]
    for label in PRODUCT_LABELS:
        args.extend(("--label", label))
    result = run_gh(*args)
    issue_url = result.stdout.strip().splitlines()[-1]
    number = int(issue_url.rstrip("/").rsplit("/", 1)[-1])
    markers[marker] = number
    print(f"created E2E issue #{number}: {failure.title}")


def create_or_update_infrastructure_issue(
    artifacts: list[str], markers: dict[str, int]
) -> None:
    """Preserve discovery setup failures that never reached Playwright results."""
    if not artifacts:
        return
    fingerprint = hashlib.sha256(b"chromium-discovery-missing-results").hexdigest()[:16]
    marker = f"<!-- chromium-discovery-failure:{fingerprint} -->"
    evidence = evidence_header(", ".join(artifacts))
    details = (
        f"{evidence}\n\n"
        "The following discovery shard artifacts did not contain `results.json`:\n\n"
        + "\n".join(f"- `{artifact}`" for artifact in artifacts)
        + "\n\nInspect the preserved backend logs and run metadata before changing product code."
    )
    existing = markers.get(marker)
    if existing is not None:
        run_gh("issue", "comment", str(existing), "--body", f"Fresh discovery infrastructure evidence:\n\n{details}")
        print(f"updated existing E2E infrastructure issue #{existing}")
        return

    body = (
        f"{marker}\n\n"
        "Scheduled Chromium discovery failed before durable Playwright JSON results were produced. "
        "This is infrastructure work unless the preserved evidence proves a product defect.\n\n"
        f"{details}"
    )
    args = [
        "issue",
        "create",
        "--title",
        "E2E infrastructure: discovery failed before Playwright results",
        "--body",
        body,
    ]
    for label in INFRA_LABELS:
        args.extend(("--label", label))
    result = run_gh(*args)
    issue_url = result.stdout.strip().splitlines()[-1]
    number = int(issue_url.rstrip("/").rsplit("/", 1)[-1])
    markers[marker] = number
    print(f"created E2E infrastructure issue #{number}")


def main() -> int:
    """Classify persisted discovery evidence without masking the original test result."""
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default="discovery-input")
    args = parser.parse_args()
    root = Path(args.root)
    if not root.exists():
        raise SystemExit(f"discovery artifact root does not exist: {root}")

    ensure_labels()
    failures, missing_results = collect_failures(root)
    markers = open_issue_markers()
    for failure in failures:
        create_or_update_product_issue(failure, markers)
    create_or_update_infrastructure_issue(missing_results, markers)
    print(
        f"classified Chromium discovery: {len(failures)} product failures, "
        f"{len(missing_results)} shards without Playwright results"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
