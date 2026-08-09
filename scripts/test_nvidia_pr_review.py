#!/usr/bin/env python3
"""Compare direct NVIDIA NIM code reviews for one GitHub pull request."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

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
    output_dir: Path
    classification: str


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "CHANGES_REQUIRED"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "body": {"type": "string"},
                    "suggestion": {"type": ["string", "null"]},
                },
                "required": ["path", "line", "body"],
            },
        },
    },
    "required": ["verdict", "findings"],
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_review_file",
            "description": "Write the initial structured PR review to review.json.",
            "parameters": {
                "type": "object",
                "properties": {"review": REVIEW_SCHEMA},
                "required": ["review"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_review_file",
            "description": "Replace review.json after checking and improving its review.",
            "parameters": {
                "type": "object",
                "properties": {
                    "review": REVIEW_SCHEMA,
                    "edit_marker": {
                        "type": "string",
                        "description": "A short description of the edit or verification performed.",
                    },
                },
                "required": ["review", "edit_marker"],
            },
        },
    },
]


def _model_slug(model: str) -> str:
    """Return a filesystem-safe model identifier."""
    return re.sub(r"[^A-Za-z0-9._-]+", "__", model).strip("._-")


def _append_log(log_file: Path, event: str, payload: object) -> None:
    """Append one timestamped event to a model's durable JSONL log."""
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event,
        "payload": payload,
    }
    with log_file.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def _write_json(target: Path, payload: object) -> None:
    """Write readable JSON to a durable result file."""
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


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


def _request_nim(
    model: str,
    api_key: str,
    messages: list[dict[str, object]],
    required_tool: str,
    timeout_seconds: float,
    log_file: Path,
) -> dict[str, object]:
    """Send one NIM request, retrying a rate limit once."""
    request_payload: dict[str, object] = {
        "model": model.removeprefix("nvidia/"),
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": {"type": "function", "function": {"name": required_tool}},
        "temperature": 0.1,
        "max_tokens": 4096,
    }
    for attempt in range(2):
        _append_log(log_file, "request", {"attempt": attempt + 1, "payload": request_payload})
        response = httpx.post(
            NVIDIA_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=request_payload,
            timeout=httpx.Timeout(timeout_seconds),
        )
        _append_log(
            log_file,
            "http_response",
            {"attempt": attempt + 1, "status_code": response.status_code, "body": response.text},
        )
        if response.status_code != 429 or attempt == 1:
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("NVIDIA response was not an object")
            return payload
        retry_after = response.headers.get("Retry-After", "2")
        try:
            delay = min(float(retry_after), 15.0)
        except ValueError:
            delay = 2.0
        _append_log(log_file, "rate_limit_retry", {"delay_seconds": delay})
        time.sleep(delay)
    raise RuntimeError("unreachable NIM retry state")


def _assistant_message(payload: dict[str, object]) -> dict[str, object]:
    """Extract one assistant message from an OpenAI-compatible response."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("NVIDIA response had no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("NVIDIA response had no assistant message")
    return message


def _tool_arguments(message: dict[str, object], expected_name: str) -> tuple[str, dict[str, object]]:
    """Extract and decode one expected tool call from an assistant message."""
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or not calls or not isinstance(calls[0], dict):
        raise ValueError(f"model did not call {expected_name}")
    call = calls[0]
    call_id = call.get("id")
    function = call.get("function")
    if not isinstance(call_id, str) or not isinstance(function, dict):
        raise ValueError("model returned a malformed tool call")
    if function.get("name") != expected_name or not isinstance(function.get("arguments"), str):
        raise ValueError(f"model called the wrong tool instead of {expected_name}")
    arguments = json.loads(function["arguments"])
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments were not an object")
    return call_id, arguments


def _review_from_arguments(arguments: dict[str, object]) -> dict[str, object]:
    """Extract a structured review object from tool arguments."""
    review = arguments.get("review")
    if not isinstance(review, dict):
        raise ValueError("tool call did not provide a review object")
    if not all(isinstance(key, str) for key in review):
        raise ValueError("review object contained a non-string key")
    return {str(key): value for key, value in review.items()}


def _classification(error: Exception) -> str:
    """Classify a provider or capability failure."""
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    if isinstance(error, httpx.HTTPStatusError):
        if error.response.status_code == 429:
            return "rate_limited"
        if error.response.status_code in {404, 410}:
            return "unavailable"
        return "provider_error"
    text = str(error)
    if "did not call" in text or "wrong tool" in text or "malformed tool" in text:
        return "tool_call_not_emitted"
    return "invalid_review"


def _review_model(
    model: str,
    api_key: str,
    prompt: str,
    commentable: dict[str, set[int]],
    timeout_seconds: float,
    output_root: Path,
) -> ModelResult:
    """Test one model's two-turn write/edit tool use and validate its review."""
    started = time.monotonic()
    model_dir = output_root / _model_slug(model)
    model_dir.mkdir(parents=True, exist_ok=True)
    log_file = model_dir / "raw.log"
    capabilities_file = model_dir / "capabilities.json"
    review_file = model_dir / "review.json"
    capabilities: dict[str, object] = {
        "model": model,
        "plain_review_valid": False,
        "write_tool_called": False,
        "review_file_written": False,
        "edit_tool_called": False,
        "review_file_changed": False,
        "structured_review_valid": False,
    }
    preliminary_verdict: str | None = None
    preliminary_findings: tuple[Finding, ...] = ()
    _append_log(log_file, "started", {"model": model, "timeout_seconds": timeout_seconds})
    try:
        messages: list[dict[str, object]] = [
            {
                "role": "system",
                "content": (
                    "You are a precise PR reviewer with file tools. First call "
                    "write_review_file. After its result, call edit_review_file."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        first_payload = _request_nim(
            model,
            api_key,
            messages,
            "write_review_file",
            timeout_seconds,
            log_file,
        )
        first_message = _assistant_message(first_payload)
        plain_content = first_message.get("content")
        if isinstance(plain_content, str):
            try:
                preliminary_verdict, preliminary_findings = _parse_review(
                    plain_content,
                    commentable,
                )
                capabilities["plain_review_valid"] = True
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        first_id, first_arguments = _tool_arguments(first_message, "write_review_file")
        capabilities["write_tool_called"] = True
        initial_review = _review_from_arguments(first_arguments)
        _write_json(review_file, initial_review)
        initial_text = review_file.read_text(encoding="utf-8")
        capabilities["review_file_written"] = True

        messages.extend(
            [
                first_message,
                {
                    "role": "tool",
                    "tool_call_id": first_id,
                    "content": json.dumps({"ok": True, "path": "review.json"}),
                },
                {
                    "role": "user",
                    "content": (
                        "Re-check the diff and the review you wrote. Now call edit_review_file "
                        "with the final review and a non-empty edit_marker, even if the findings "
                        "remain unchanged."
                    ),
                },
            ],
        )
        remaining = timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise httpx.TimeoutException("model exhausted its whole-job timeout before edit turn")
        second_payload = _request_nim(
            model,
            api_key,
            messages,
            "edit_review_file",
            remaining,
            log_file,
        )
        second_message = _assistant_message(second_payload)
        _second_id, second_arguments = _tool_arguments(second_message, "edit_review_file")
        capabilities["edit_tool_called"] = True
        final_review = _review_from_arguments(second_arguments)
        marker = second_arguments.get("edit_marker")
        if not isinstance(marker, str) or not marker.strip():
            raise ValueError("edit tool did not provide a non-empty edit_marker")
        final_review["_agent_edit_marker"] = marker.strip()
        _write_json(review_file, final_review)
        capabilities["review_file_changed"] = review_file.read_text(encoding="utf-8") != initial_text
        if not capabilities["review_file_changed"]:
            raise ValueError("edit tool did not change review.json")
        verdict, findings = _parse_review(json.dumps(final_review), commentable)
        capabilities["structured_review_valid"] = True
        capabilities["classification"] = "passed"
        capabilities["elapsed_seconds"] = time.monotonic() - started
        _write_json(capabilities_file, capabilities)
        _append_log(log_file, "completed", capabilities)
        return ModelResult(
            model=model,
            status="completed",
            verdict=verdict,
            findings=findings,
            elapsed_seconds=time.monotonic() - started,
            detail="two-turn write/edit review accepted",
            output_dir=model_dir,
            classification="passed",
        )
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        classification = _classification(error)
        capabilities["classification"] = classification
        capabilities["elapsed_seconds"] = time.monotonic() - started
        capabilities["error"] = str(error)
        _write_json(capabilities_file, capabilities)
        _append_log(log_file, "failed", capabilities)
        return ModelResult(
            model=model,
            status="failed",
            verdict=preliminary_verdict,
            findings=preliminary_findings,
            elapsed_seconds=time.monotonic() - started,
            detail=str(error),
            output_dir=model_dir,
            classification=classification,
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
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Maximum simultaneous models (default: 3)",
    )
    parser.add_argument("--force", action="store_true", help="Rerun completed model/head results")
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="PATH:LINE",
        help="Known defect location; repeat to measure review recall",
    )
    parser.add_argument("--post", action="store_true", help="Post validated inline findings")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".nvidia-review-results"),
        help="Root directory for per-model logs and review files",
    )
    return parser


def _load_completed_result(
    model: str,
    model_dir: Path,
    commentable: dict[str, set[int]],
) -> ModelResult | None:
    """Load a prior successful result for this exact PR head, when present."""
    capabilities_file = model_dir / "capabilities.json"
    review_file = model_dir / "review.json"
    if not capabilities_file.exists() or not review_file.exists():
        return None
    try:
        capabilities = json.loads(capabilities_file.read_text(encoding="utf-8"))
        if not isinstance(capabilities, dict) or capabilities.get("classification") != "passed":
            return None
        verdict, findings = _parse_review(review_file.read_text(encoding="utf-8"), commentable)
        elapsed = capabilities.get("elapsed_seconds", 0.0)
        if not isinstance(elapsed, int | float):
            elapsed = 0.0
        return ModelResult(
            model=model,
            status="completed",
            verdict=verdict,
            findings=findings,
            elapsed_seconds=float(elapsed),
            detail="resumed exact-head result",
            output_dir=model_dir,
            classification="passed",
        )
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def _parse_expected_locations(values: list[str]) -> set[tuple[str, int]]:
    """Parse repeatable PATH:LINE known-defect locations."""
    locations: set[tuple[str, int]] = set()
    for value in values:
        path, separator, raw_line = value.rpartition(":")
        if not separator or not path:
            raise ValueError(f"invalid expected finding {value!r}; use PATH:LINE")
        locations.add((path, int(raw_line)))
    return locations


def _review_quality(result: ModelResult, expected: set[tuple[str, int]]) -> str:
    """Score review usefulness separately from agent tool compatibility."""
    if result.verdict is None:
        return "no_valid_review"
    if not expected:
        return "valid_unscored"
    actual = {(finding.path, finding.line) for finding in result.findings}
    if expected <= actual:
        return "known_defects_found"
    return "missed_known_defect"


def _write_summary(
    output_root: Path,
    results: list[ModelResult],
    expected: set[tuple[str, int]],
) -> None:
    """Write aggregate machine-readable JSON and CSV result tables."""
    rows = [
        {
            "model": result.model,
            "status": result.status,
            "classification": result.classification,
            "review_quality": _review_quality(result, expected),
            "verdict": result.verdict,
            "findings": len(result.findings),
            "elapsed_seconds": round(result.elapsed_seconds, 3),
            "detail": result.detail,
            "output_dir": str(result.output_dir),
        }
        for result in sorted(results, key=lambda item: (item.classification != "passed", item.model))
    ]
    _write_json(output_root / "summary.json", rows)
    with (output_root / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["model"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    """Run all discovered NVIDIA reviews and print a comparison report.

    Returns:
        Zero when at least one model completed a valid review, otherwise one.
    """
    args = _parser().parse_args()
    if args.concurrency < 1 or args.timeout <= 0:
        print("--concurrency and --timeout must be positive", file=sys.stderr)
        return 2
    try:
        expected = _parse_expected_locations(args.expect)
    except (TypeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
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
    output_root = args.output_dir / f"pr-{pr_data['number']}-{str(pr_data['headRefOid'])[:12]}"
    output_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        output_root / "run.json",
        {
            "repo": repo,
            "pr": pr_data["number"],
            "url": pr_data["url"],
            "head": pr_data["headRefOid"],
            "models": models,
            "timeout_seconds": args.timeout,
            "concurrency": args.concurrency,
            "expected_findings": [f"{path}:{line}" for path, line in sorted(expected)],
        },
    )
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
    print(f"Results: {output_root.resolve()}")
    results: list[ModelResult] = []
    pending_models: list[str] = []
    for model in models:
        resumed = None
        if not args.force:
            resumed = _load_completed_result(model, output_root / _model_slug(model), commentable)
        if resumed is not None:
            results.append(resumed)
            print(f"[resumed  ] {model} -> {resumed.output_dir}", flush=True)
        else:
            pending_models.append(model)
            print(f"[queued   ] {model}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(
                _review_model,
                model,
                api_key,
                prompt,
                commentable,
                args.timeout,
                output_root,
            ): model
            for model in pending_models
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            verdict = result.verdict or "NO_VERDICT"
            print(
                f"[{result.classification:14}] {result.elapsed_seconds:7.1f}s {verdict:16} "
                f"{result.model} -> {result.output_dir}",
                flush=True,
            )

    _write_summary(output_root, results, expected)

    completed = 0
    for result in sorted(results, key=lambda item: item.elapsed_seconds):
        verdict = result.verdict or "NO_VERDICT"
        print(
            f"[{result.classification:14}] {result.elapsed_seconds:7.1f}s {verdict:16} "
            f"{result.model} ({len(result.findings)} findings, "
            f"quality={_review_quality(result, expected)}) - {result.detail}",
        )
        print(f"  log: {result.output_dir / 'raw.log'}")
        for finding in result.findings:
            print(f"  {finding.path}:{finding.line}: {finding.body}")
        if result.status == "completed":
            completed += 1
            if args.post:
                current = json.loads(
                    _run(
                        [
                            "gh",
                            "pr",
                            "view",
                            str(pr_data["number"]),
                            "--repo",
                            repo,
                            "--json",
                            "headRefOid",
                        ],
                    ),
                )
                if current.get("headRefOid") != pr_data["headRefOid"]:
                    raise RuntimeError("PR head moved after review; refusing to post stale comments")
                _post_findings(repo, int(pr_data["number"]), str(pr_data["headRefOid"]), result)

    if not args.post:
        print("Dry run only. Add --post to create validated inline review comments.")
    return 0 if completed else 1


if __name__ == "__main__":
    raise SystemExit(main())
