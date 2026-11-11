"""Regression coverage for the trusted local Ollama review protocol."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/local_review_contract.py"
SPEC = importlib.util.spec_from_file_location("local_review_contract", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract
SPEC.loader.exec_module(contract)

HEAD = "a" * 40


def target(*, state: str = "open", draft: bool = False,
           head: str = HEAD, body: str = "Closes #4964.",
           labels: list[dict[str, str]] | None = None) -> dict:
    return {
        "state": state,
        "draft": draft,
        "head": {"sha": head, "ref": "fix/4964-ollama-review-json-contract"},
        "body": body,
        "labels": labels or [{"name": "factory:unowned"}],
    }


def response(content: str, finish: str = "stop") -> dict:
    return {
        "choices": [{"finish_reason": finish, "message": {"content": content}}],
        "usage": {"completion_tokens": 1400},
    }


def test_target_uses_canonical_link_and_preserves_exact_head() -> None:
    assert contract.target(target(), expected_head=HEAD) == {
        "head": HEAD, "issue": 4964, "non_closing": False
    }
    part = target(body="Part of #4847.")
    assert contract.target(part)["non_closing"] is True


@pytest.mark.parametrize(
    "pr, expected",
    [
        (target(state="closed"), "not an open"),
        (target(draft=True), "not an open"),
        (target(head="b" * 40), "head changed"),
        (target(body="A PR without an issue link"), "no canonical linked issue"),
        (target(labels=[{"name": "factory:41"}]), "active factory lease"),
    ],
)
def test_closed_stale_unlinked_or_claimed_target_is_never_reviewed(
    pr: dict, expected: str
) -> None:
    with pytest.raises(contract.ReviewContractError, match=expected):
        contract.target(pr, expected_head=HEAD if pr["head"]["sha"] != HEAD else None)


def test_openai_compatible_json_mode_has_rubric_aware_output_budget() -> None:
    request = contract.make_request("qwen2.5-coder:7b", "Review actual diff", 12)
    assert request["response_format"] == {"type": "json_object"}
    assert request["temperature"] == 0
    assert request["stream"] is False
    assert request["max_tokens"] == 4200
    assert contract.make_request("qwen2.5-coder:7b", "x", 1)["max_tokens"] == 4096
    assert contract.make_request("qwen2.5-coder:7b", "x", 100)["max_tokens"] == 8192


def test_complete_json_approval_is_parsed_without_inventing_acceptance() -> None:
    content = (
        '{"verdict":"APPROVE","reason":"All inspected changes satisfy the linked issue.",'
        '"acceptance":{"issue":4964,"items":[]}}'
    )
    parsed = contract.parse_response(response(content))
    assert parsed["verdict"] == "APPROVE"
    assert parsed["acceptance"]["issue"] == 4964


def test_bounded_truncation_is_not_silently_salvaged() -> None:
    bad = response('{"verdict":"APPROVE","reason":"unfinished"', finish="length")
    with pytest.raises(contract.ReviewContractError, match="token limit"):
        contract.parse_response(bad)
    with pytest.raises(contract.ReviewContractError, match="malformed review JSON"):
        contract.parse_response(response('{"verdict":"APPROVE","reason":'))


def test_reject_requires_actionable_reason_and_cannot_fake_approval() -> None:
    with pytest.raises(contract.ReviewContractError, match="substantive review reason"):
        contract.parse_response(response('{"verdict":"REJECT","reason":"No"}'))
    parsed = contract.parse_response(response(
        '{"verdict":"REJECT","reason":"tests/test_example.py does not verify expected behavior."}'
    ))
    assert parsed["verdict"] == "REJECT"
    with pytest.raises(contract.ReviewContractError, match="structured issue acceptance"):
        contract.parse_response(response(
            '{"verdict":"APPROVE","reason":"All inspected changes satisfy the linked issue."}'
        ))


def test_script_uses_controller_and_never_claims_truncated_or_stale_review() -> None:
    script = (ROOT / ".github/scripts/local-ollama-review.sh").read_text()
    workflow = (ROOT / ".github/workflows/local-ollama-review.yml").read_text()
    assert 'ISSUE="4825"' not in script
    assert 'local_review_contract.py target' in script
    assert '--expected-head "$HEAD"' in script
    assert 'local_review_contract.py response /tmp/resp.json' in script
    assert 'controller_verdict=repair' in script
    assert 'jq \'.max_tokens = 8192\'' in script
    assert 'gh_retry gh workflow run factory-ready-merge-drain.yml' in script
    assert 'gh pr merge' not in script
    assert 'timeout-minutes: 45' in workflow


def test_review_shell_has_valid_bash_syntax() -> None:
    import subprocess

    result = subprocess.run(
        ["bash", "-n", str(ROOT / ".github/scripts/local-ollama-review.sh")],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
