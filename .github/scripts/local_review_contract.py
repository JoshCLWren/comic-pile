"""Fail-closed OpenAI-compatible review contract for the trusted Ollama bridge.

This module never attests reviews or changes GitHub state. The trusted
factory-review-controller remains the only authority for review transitions.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

HEAD_RE = re.compile(r"^[0-9a-f]{40}$")
OWNER_RE = re.compile(r"^factory:[0-9]+$")


class ReviewContractError(ValueError):
    """The target or model response is unsuitable for a trusted review."""


def _issue_policy() -> Any:
    path = Path(__file__).with_name("factory_issue_acceptance.py")
    spec = importlib.util.spec_from_file_location("local_review_issue_acceptance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def target(pr: Mapping[str, Any], expected_head: str | None = None) -> dict[str, Any]:
    """Resolve an open, unclaimed exact-head PR and its canonical linked issue."""
    if pr.get("state") != "open" or pr.get("draft") is not False:
        raise ReviewContractError("review target is not an open, non-draft PR")
    head = pr.get("head", {}).get("sha") if isinstance(pr.get("head"), dict) else None
    if not isinstance(head, str) or not HEAD_RE.fullmatch(head):
        raise ReviewContractError("review target has no valid head SHA")
    if expected_head is not None and head != expected_head:
        raise ReviewContractError("review target head changed during inference")
    labels = pr.get("labels") or []
    if not isinstance(labels, list):
        raise ReviewContractError("review target labels are unavailable")
    owned = [
        item.get("name") for item in labels
        if isinstance(item, dict) and OWNER_RE.fullmatch(str(item.get("name", "")))
    ]
    if owned:
        raise ReviewContractError(
            "PR already has an active factory lease; do not steal another review"
        )
    branch = pr.get("head", {}).get("ref", "")
    body = pr.get("body") or ""
    if not isinstance(branch, str) or not isinstance(body, str):
        raise ReviewContractError("review target branch/body unavailable")
    issue, non_closing = _issue_policy().linked_issue_mode(branch, body)
    if issue is None or issue <= 0:
        raise ReviewContractError("review target has no canonical linked issue")
    return {"head": head, "issue": issue, "non_closing": non_closing}


def make_request(model: str, prompt: str, criteria_count: int) -> dict[str, Any]:
    """Give the full acceptance rubric room to finish and require JSON mode."""
    if criteria_count <= 0:
        raise ReviewContractError("linked issue has no criteria to review")
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "stream": False,
        "response_format": {"type": "json_object"},
        "max_tokens": min(8192, max(4096, 350 * criteria_count)),
    }


def parse_response(response: Mapping[str, Any]) -> dict[str, Any]:
    """Accept complete semantic JSON only; never repair/trust a truncated blob."""
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ReviewContractError("provider returned no unique review choice")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ReviewContractError("provider returned a malformed choice")
    finish_reason = choice.get("finish_reason")
    if finish_reason == "length":
        used = (response.get("usage") or {}).get("completion_tokens", "?")
        raise ReviewContractError(
            f"review output hit its token limit after {used} completion tokens"
        )
    if finish_reason not in (None, "stop"):
        raise ReviewContractError(f"review terminated abnormally: {finish_reason}")
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ReviewContractError("provider returned no review JSON content")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ReviewContractError(
            f"model produced malformed review JSON at character {exc.pos}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ReviewContractError("model response must be a JSON object")
    verdict = str(parsed.get("verdict", "")).upper()
    reason = parsed.get("reason")
    if verdict not in {"APPROVE", "REJECT"}:
        raise ReviewContractError("model response lacks APPROVE/REJECT verdict")
    if not isinstance(reason, str) or len(reason.strip()) < 30:
        raise ReviewContractError("model response needs a substantive review reason")
    if verdict == "APPROVE" and not isinstance(parsed.get("acceptance"), dict):
        raise ReviewContractError("approval lacks structured issue acceptance")
    parsed["verdict"] = verdict
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    tgt = sub.add_parser("target")
    tgt.add_argument("file")
    tgt.add_argument("--expected-head")
    response = sub.add_parser("response")
    response.add_argument("file")
    args = parser.parse_args()
    try:
        with open(args.file, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ReviewContractError("input must be a JSON object")
        if args.command == "target":
            result = target(data, expected_head=args.expected_head)
        else:
            result = parse_response(data)
    except (OSError, json.JSONDecodeError, ReviewContractError) as exc:
        parser.exit(2, f"local review contract: {exc}\n")
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
