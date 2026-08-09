#!/usr/bin/env python3
"""Compare direct NVIDIA NIM code reviews for one GitHub pull request."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass

import httpx

from scripts.select_fcm_nvidia_model import select_models


NVIDIA_CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
HUNK_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class Finding:
    """One validated inline review finding."""

    path: str
    line: int
    body: str
    suggestion: str | None = None


@dataclass(frozen=True)
class ModelResult:
    """Review result and timing for one NVIDIA model."""

    model: str
    status: str
    verdict: str | None
    findings: tuple[Finding, ...]
    elapsed_seconds: float
    detail: str


def _run(command: list[str], *, input_text: str | None = None) -> str:
    """Run a command and return stdout.

    Args:
        command: Command and arguments to execute.
        input_text: Optional standard input.

    Returns:
        Captured standard output.

    Raises:
        RuntimeError: When the command fails.
    """
    result = subprocess.run(
        command,
        check=False,
        input=input_text,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"{' '.join(command)} failed: {detail}")
    return result.stdout


def _discover_models(limit: int | None) -> list[str]:
    """Discover ranked NVIDIA chat candidates through FCM.

    Args:
        limit: Maximum models to return, or ``None`` for every candidate.

    Returns:
        Provider-qualified model identifiers.
    """
    raw_output = _run(
        [
            "free-coding-models",
            "--json",
            "--origin",
            "nvidia",
            "--hide-unconfigured",
            "--best",
            "--no-telemetry",
        ],
    )
    models = select_models(raw_output)
    return models if limit is None else models[:limit]


def _changed_lines(patch: str) -> dict[str, set[int]]:
    """Return added right-side line numbers for every changed file.

    Args:
        patch: Unified pull-request diff.

    Returns:
        Mapping from repository paths to commentable added lines.
    """
    changed: dict[str, set[int]] = {}
    path: str | None = None
    right_line: int | None = None
    for raw_line in patch.splitlines():
        if raw_line.startswith("+++ b/"):
            path = raw_line[6:]
            changed.setdefault(path, set())
            continue
        hunk = HUNK_PATTERN.match(raw_line)
        if hunk:
            right_line = int(hunk.group(1))
            continue
        if path is None or right_line is None:
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            changed[path].add(right_line)
            right_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            continue
        else:
            right_line += 1
    return changed


def _extract_json(content: str) -> object:
    """Extract one JSON object from a model response.

    Args:
        content: Raw assistant response.

    Returns:
        Parsed JSON value.

    Raises:
        ValueError: When no JSON object is present.
    """
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end < start:
        raise ValueError("response did not contain a JSON object")
    return json.loads(content[start : end + 1])


def _parse_review(content: str, commentable: dict[str, set[int]]) -> tuple[str, tuple[Finding, ...]]:
    """Parse and validate a structured model review.

    Args:
        content: Raw model response.
        commentable: Allowed right-side diff locations.

    Returns:
        Normalized verdict and validated findings.

    Raises:
        ValueError: When the response schema or a location is invalid.
    """
    payload = _extract_json(content)
    if not isinstance(payload, dict):
        raise ValueError("review payload was not an object")
    verdict = payload.get("verdict")
    raw_findings = payload.get("findings")
    if verdict not in {"PASS", "CHANGES_REQUIRED"} or not isinstance(raw_findings, list):
        raise ValueError("review payload had an invalid verdict or findings list")

    findings: list[Finding] = []
    for raw_finding in raw_findings:
        if not isinstance(raw_finding, dict):
            raise ValueError("finding was not an object")
        path = raw_finding.get("path")
        line = raw_finding.get("line")
        body = raw_finding.get("body")
        suggestion = raw_finding.get("suggestion")
        if not isinstance(path, str) or not isinstance(line, int) or not isinstance(body, str):
            raise ValueError("finding path, line, or body had the wrong type")
        if line not in commentable.get(path, set()):
            raise ValueError(f"finding targeted non-added diff location {path}:{line}")
        if suggestion is not None and not isinstance(suggestion, str):
            raise ValueError("finding suggestion was not text")
        findings.append(Finding(path=path, line=line, body=body.strip(), suggestion=suggestion))

    normalized = "CHANGES_REQUIRED" if findings else "PASS"
    if verdict != normalized:
        raise ValueError(f"verdict {verdict} contradicted {len(findings)} validated findings")
    return normalized, tuple(findings)


def _review_model(
    model: str,
    api_key: str,
    prompt: str,
    commentable: dict[str, set[int]],
    timeout_seconds: float,
) -> ModelResult:
    """Request and validate one direct NIM review.

    Args:
        model: Provider-qualified NVIDIA model.
        api_key: NVIDIA API key.
        prompt: Complete review prompt.
        commentable: Allowed inline comment locations.
        timeout_seconds: Whole HTTP request timeout.

    Returns:
        Comparable model result; provider failures are represented, not raised.
    """
    started = time.monotonic()
    try:
        response = httpx.post(
            NVIDIA_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model.removeprefix("nvidia/"),
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a precise pull-request reviewer. Return JSON only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 4096,
            },
            timeout=httpx.Timeout(timeout_seconds),
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("NVIDIA response content was not text")
        verdict, findings = _parse_review(content, commentable)
        return ModelResult(
            model=model,
            status="completed",
            verdict=verdict,
            findings=findings,
            elapsed_seconds=time.monotonic() - started,
            detail="structured review accepted",
        )
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        return ModelResult(
            model=model,
            status="failed",
            verdict=None,
            findings=(),
            elapsed_seconds=time.monotonic() - started,
            detail=str(error),
        )


def _post_findings(repo: str, pr_number: int, head: str, result: ModelResult) -> None:
    """Post validated findings as inline GitHub comments.

    Args:
        repo: GitHub ``owner/name`` repository.
        pr_number: Pull request number.
        head: Exact reviewed commit.
        result: Completed model review.
    """
    for finding in result.findings:
        body = f"[NVIDIA NIM `{result.model}`] {finding.body}"
        if finding.suggestion:
            body += f"\n\n```suggestion\n{finding.suggestion}\n```"
        _run(
            [
                "gh",
                "api",
                "--method",
                "POST",
                f"repos/{repo}/pulls/{pr_number}/comments",
                "-f",
                f"body={body}",
                "-f",
                f"commit_id={head}",
                "-f",
                f"path={finding.path}",
                "-F",
                f"line={finding.line}",
                "-f",
                "side=RIGHT",
            ],
        )


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns:
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr", help="Pull request number or URL")
    parser.add_argument("--repo", help="GitHub owner/name; defaults to the current repository")
    parser.add_argument("--max-models", type=int, help="Limit candidates for a shorter experiment")
    parser.add_argument("--timeout", type=float, default=300, help="Seconds allowed per model")
    parser.add_argument("--post", action="store_true", help="Post validated inline findings")
    return parser


def main() -> int:
    """Run all discovered NVIDIA reviews and print a comparison report.

    Returns:
        Zero when at least one model completed a valid review, otherwise one.
    """
    args = _parser().parse_args()
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        print("NVIDIA_API_KEY is required", file=sys.stderr)
        return 2
    repo = args.repo or json.loads(_run(["gh", "repo", "view", "--json", "nameWithOwner"]))[
        "nameWithOwner"
    ]
    pr_data = json.loads(
        _run(
            [
                "gh",
                "pr",
                "view",
                args.pr,
                "--repo",
                repo,
                "--json",
                "number,title,body,headRefOid,url",
            ],
        ),
    )
    patch = _run(["gh", "pr", "diff", str(pr_data["number"]), "--repo", repo, "--patch"])
    commentable = _changed_lines(patch)
    models = _discover_models(args.max_models)
    prompt = (
        f"Review PR #{pr_data['number']}: {pr_data['title']}\n\n"
        f"Description:\n{pr_data.get('body') or '(none)'}\n\n"
        "Return exactly this JSON shape:\n"
        '{"verdict":"PASS|CHANGES_REQUIRED","findings":'
        '[{"path":"path","line":123,"body":"actionable explanation",'
        '"suggestion":"optional replacement text"}]}\n'
        "Only report real defects. Every finding must target an added (+) right-side line in the diff. "
        "Use an empty findings list for PASS.\n\n"
        f"Exact unified diff:\n{patch}"
    )

    print(f"Reviewing {pr_data['url']} at {pr_data['headRefOid']} with {len(models)} models")
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(models)) as executor:
        futures = [
            executor.submit(
                _review_model,
                model,
                api_key,
                prompt,
                commentable,
                args.timeout,
            )
            for model in models
        ]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]

    completed = 0
    for result in sorted(results, key=lambda item: item.elapsed_seconds):
        verdict = result.verdict or "NO_VERDICT"
        print(
            f"[{result.status:9}] {result.elapsed_seconds:7.1f}s {verdict:16} "
            f"{result.model} ({len(result.findings)} findings) - {result.detail}",
        )
        for finding in result.findings:
            print(f"  {finding.path}:{finding.line}: {finding.body}")
        if result.status == "completed":
            completed += 1
            if args.post:
                _post_findings(repo, int(pr_data["number"]), str(pr_data["headRefOid"]), result)

    if not args.post:
        print("Dry run only. Add --post to create validated inline review comments.")
    return 0 if completed else 1


if __name__ == "__main__":
    raise SystemExit(main())
