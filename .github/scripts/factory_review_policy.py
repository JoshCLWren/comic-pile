"""Pure semantic review authorization policy for ComicPile factories."""
from __future__ import annotations

import re
from collections.abc import Iterable

REVIEW_MARKER_RE = re.compile(
    r"^<!-- comic-pile-factory-semantic-review-v1:"
    r"pr-(?P<pr>\d+):head-(?P<head>[0-9a-f]{40}):"
    r"reviewer-(?P<reviewer>\d+):producer-(?P<producer>\d+|unknown):"
    r"verdict-(?P<verdict>approve|repair|reject|obsolete|duplicate|superseded|delivered) -->$"
)
BRANCH_PRODUCER_RE = re.compile(r"^factory/(?P<worker>\d+)-\d+-")
BODY_PRODUCER_RE = re.compile(
    r"(?m)^Worker:\s*opencode-(?:free-model|nvidia|omniroute)-factory-"
    r"(?P<worker>\d+)\s*$"
)
HEAD_CONTRIBUTOR_RE = re.compile(
    r"^<!--\s*comic-pile-factory-head-contributor-v1:"
    r"pr-(?P<pr>\d+):head-(?P<head>[0-9a-f]{40}):"
    r"worker-(?P<worker>\d+):epoch-(?P<epoch>\d+)\s*-->$"
)


def classify_ci_reconciliation(
    *,
    checks_decision: str,
    authorized: bool,
    mechanical_decision: str | None = None,
) -> str:
    """Classify one exact-head CI-stage PR without invoking a worker.

    The caller supplies decisions from the authoritative GitHub reads and
    gate functions.  This pure boundary makes the lifecycle ordering explicit
    and keeps unknown state fail-closed.
    """
    if checks_decision == "retry":
        return "retry-ci"
    if checks_decision == "deny":
        return "repair-ci"
    if checks_decision != "pass":
        return "retry-ci"
    if not authorized:
        return "review"
    if mechanical_decision == "pass":
        return "ready"
    if mechanical_decision == "deny":
        return "changes-requested"
    return "retry-ci"


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
    if verdict not in {"approve", "repair", "reject", "obsolete", "duplicate", "superseded", "delivered"}:
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


def parse_head_contributor_marker(line: str) -> dict[str, str] | None:
    """Parse one exact head contributor marker line."""
    match = HEAD_CONTRIBUTOR_RE.fullmatch(line.strip())
    return match.groupdict() if match else None


def head_contributor_marker(
    *,
    pr: int,
    head: str,
    worker: str,
    epoch: int,
) -> str:
    """Build one controller-authored head contributor marker."""
    return (
        "<!-- comic-pile-factory-head-contributor-v1:"
        f"pr-{pr}:head-{head}:worker-{worker}:epoch-{epoch} -->"
    )


def current_head_contributors(
    comments: Iterable[str],
    *,
    pr: int,
    head: str,
) -> set[str]:
    """Return distinct factory workers that contributed to one exact PR head."""
    contributors: set[str] = set()
    for body in comments:
        for line in str(body or "").splitlines():
            marker = parse_head_contributor_marker(line)
            if not marker:
                continue
            if int(marker["pr"]) != pr or marker["head"] != head:
                continue
            contributors.add(marker["worker"])
    return contributors


def semantic_repair_heads(
    comments: Iterable[str],
    *,
    pr: int,
) -> set[str]:
    """Return distinct PR heads that received an authoritative repair verdict."""
    heads: set[str] = set()
    for body in comments:
        first_line = str(body or "").splitlines()[0] if body else ""
        marker = parse_review_marker(first_line)
        if not marker or int(marker["pr"]) != pr:
            continue
        if marker["verdict"] == "repair":
            heads.add(marker["head"])
    return heads


def semantic_terminal_heads(
    comments: Iterable[str],
    *,
    pr: int,
) -> set[str]:
    """Return distinct PR heads that received an authoritative terminal verdict."""
    heads: set[str] = set()
    for body in comments:
        first_line = str(body or "").splitlines()[0] if body else ""
        marker = parse_review_marker(first_line)
        if not marker or int(marker["pr"]) != pr:
            continue
        if marker["verdict"] in {"obsolete", "duplicate", "superseded", "delivered"}:
            heads.add(marker["head"])
    return heads


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
    contributors: set[str],
    approvers: Iterable[str],
    has_provenance: bool,
) -> bool:
    """Return whether exact-head approvals satisfy worker-independent review policy.

    A reviewer is eligible only if they are NOT in the trusted contributor set
    for the exact head being reviewed. This is a factory-identity boundary, not
    a model or provider boundary: OmniRoute may route both workers through the
    same upstream model.

    If contributor provenance is missing/malformed for a factory-mutated head,
    fail closed rather than silently treating a reviewer as independent.
    Historical PRs with genuinely missing provenance (has_provenance=False)
    require two distinct factory reviewers.
    """
    reviewer_set = set(approvers)
    if has_provenance:
        # Fail closed: reviewer must not be in the contributor set
        return any(reviewer not in contributors for reviewer in reviewer_set)
    # Historical PR without contributor provenance: require two distinct reviewers
    return len(reviewer_set) >= 2


def approval_can_promote(
    *,
    contributors: set[str],
    has_provenance: bool,
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
    # Reviewer must not be a contributor to the exact head being reviewed
    if has_provenance and reviewer in contributors:
        return False
    return head_has_authorized_approval(
        contributors=contributors,
        approvers={*prior_approvers, reviewer},
        has_provenance=has_provenance,
    )
