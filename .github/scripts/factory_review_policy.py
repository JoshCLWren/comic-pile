"""Pure semantic review authorization policy for ComicPile factories."""
from __future__ import annotations

import re
from collections.abc import Iterable

REVIEW_MARKER_RE = re.compile(
    r"^<!-- comic-pile-factory-semantic-review-v1:"
    r"pr-(?P<pr>\d+):head-(?P<head>[0-9a-f]{40}):"
    r"reviewer-(?P<reviewer>\d+):producer-(?P<producer>\d+|unknown):"
    r"verdict-(?P<verdict>approve|repair|reject) -->$"
)
BRANCH_PRODUCER_RE = re.compile(r"^factory/(?P<worker>\d+)-\d+-")
BODY_PRODUCER_RE = re.compile(
    r"(?m)^Worker:\s*opencode-free-model-factory-(?P<worker>\d+)\s*$"
)


def producer_worker_from_pr(*, branch: str | None, body: str | None) -> str | None:
    """Recover durable producer identity without inventing historical provenance."""
    if branch:
        match = BRANCH_PRODUCER_RE.match(branch)
        if match:
            return match.group("worker")
    if body:
        match = BODY_PRODUCER_RE.search(body)
        if match:
            return match.group("worker")
    return None


def review_marker(
    *,
    pr: int,
    head: str,
    reviewer: str,
    producer: str | None,
    verdict: str,
) -> str:
    """Build one controller-authored semantic review marker."""
    if verdict not in {"approve", "repair", "reject"}:
        raise ValueError(f"unsupported verdict: {verdict}")
    producer_value = producer or "unknown"
    return (
        "<!-- comic-pile-factory-semantic-review-v1:"
        f"pr-{pr}:head-{head}:reviewer-{reviewer}:producer-{producer_value}:"
        f"verdict-{verdict} -->"
    )


def parse_review_marker(line: str) -> dict[str, str] | None:
    """Parse one exact semantic review marker line."""
    match = REVIEW_MARKER_RE.fullmatch(line.strip())
    return match.groupdict() if match else None


def current_head_approvers(
    comments: Iterable[str],
    *,
    pr: int,
    head: str,
) -> set[str]:
    """Return distinct approving reviewers attested for one exact PR head."""
    reviewers: set[str] = set()
    for body in comments:
        first_line = str(body or "").splitlines()[0] if body else ""
        marker = parse_review_marker(first_line)
        if not marker:
            continue
        if int(marker["pr"]) != pr or marker["head"] != head:
            continue
        if marker["verdict"] == "approve":
            reviewers.add(marker["reviewer"])
    return reviewers


def head_has_authorized_approval(
    *,
    producer: str | None,
    approvers: Iterable[str],
) -> bool:
    """Return whether exact-head approvals satisfy independent review policy.

    New/current factory PRs normally have durable producer provenance. One
    distinct reviewer is enough for those PRs. Historical PRs with genuinely
    missing provenance require two distinct factory reviewers so the backlog
    can move without fabricating producer history.
    """
    reviewer_set = set(approvers)
    if producer is not None:
        return any(reviewer != producer for reviewer in reviewer_set)
    return len(reviewer_set) >= 2


def approval_can_promote(
    *,
    producer: str | None,
    reviewer: str,
    reviewed_head: str,
    current_head: str,
    verdict: str,
    mechanical_gates_passed: bool,
    prior_approvers: Iterable[str] = (),
) -> bool:
    """Apply the controller-side semantic promotion trust boundary."""
    if verdict != "approve":
        return False
    if reviewed_head != current_head:
        return False
    if not mechanical_gates_passed:
        return False
    if producer is not None and reviewer == producer:
        return False
    return head_has_authorized_approval(
        producer=producer,
        approvers={*prior_approvers, reviewer},
    )
