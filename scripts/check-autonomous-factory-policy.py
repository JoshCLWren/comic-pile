#!/usr/bin/env python3
"""Fail when autonomous factory policy files drift on critical invariants."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "docs" / "AUTONOMOUS_FACTORY_POLICY.md"
PROTOCOL = ROOT / "docs" / "ISSUE_EXECUTION_PROTOCOL.md"
ENTRYPOINT = ROOT / "scripts" / "comic-pile-opencode-factory.sh"


def require(text: str, needle: str, source: Path) -> None:
    if needle not in text:
        raise SystemExit(f"{source}: missing required policy text: {needle!r}")


def forbid(text: str, needle: str, source: Path) -> None:
    if needle in text:
        raise SystemExit(f"{source}: forbidden policy drift found: {needle!r}")


def validate_texts(policy: str, protocol: str, entrypoint: str) -> None:
    """Validate policy source text against the canonical delivery invariants."""
    for needle in (
        "Finish what you start. Success is measured by issues closed, not pull requests opened.",
        "A worker owns an issue, not a PR.",
        "Implement the full issue in one coherent PR whenever reasonably reviewable.",
        "Large coherent PRs are allowed and preferred",
        "Do not open planning-only, architecture-only, inventory-only, or implementation-plan PRs",
        "Writing extensive docs instead of implementing executable work is a policy failure.",
        "Do not start a new issue while an owned issue has executable remaining work.",
        "A PR merge does not release issue ownership when the parent issue still has executable remaining work.",
        "Labels, claims, comments, verdicts, PR-body edits, and ready markers do not satisfy this floor by themselves.",
        "All review, repair, and readiness decisions are tied to the exact pull-request head SHA.",
        "CI-assisted debugging is permitted",
        "CI failures, rebases, merge conflicts, test updates, review defects, browser inconvenience, and broad issues are ordinary engineering",
        "Never push directly to `main`.",
        "Never create a draft pull request unless Josh explicitly requests a draft.",
        "Never merge unless Josh explicitly orders that specific merge.",
        "Never enable auto-merge as a substitute for explicit authorization.",
    ):
        require(policy, needle, POLICY)

    for marker in (
        "comic-pile-factory-implement-claim-v3",
        "comic-pile-factory-implement-progress-v3",
        "comic-pile-factory-review-claim-v2",
        "comic-pile-factory-review-v2:<full-sha>:pass",
        "comic-pile-factory-review-v2:<full-sha>:changes-required",
        "comic-pile-factory-fix-claim-v3",
        "comic-pile-factory-fix-progress-v3",
        "comic-pile-factory-ready-v2",
        "comic-pile-factory-needs-human-v2",
        "comic-pile-factory-claim-released-v3",
    ):
        require(policy, marker, POLICY)

    require(policy, "for 45 minutes after its latest claim", POLICY)
    require(policy, "for 60 minutes after its latest claim or progress marker", POLICY)
    require(policy, "An issue implementation lease is active for 60 minutes", POLICY)
    require(policy, "Simultaneous claims are resolved by lowest GitHub comment ID.", POLICY)
    require(policy, "A pushed new SHA releases old-SHA review and repair leases.", POLICY)

    for obsolete in (
        "comic-pile-factory-fix-v2:",
        "comic-pile-factory-ready:",
        "comic-pile-factory-review-claim:",
        "HONEST STAGE FAST PATH",
    ):
        forbid(policy, obsolete, POLICY)

    require(protocol, "docs/AUTONOMOUS_FACTORY_POLICY.md", PROTOCOL)
    require(protocol, "Never create a draft pull request unless Josh explicitly requests a draft.", PROTOCOL)
    require(protocol, "Never merge without Josh's explicit authorization", PROTOCOL)
    require(protocol, "run focused local validation that directly exercises the change", PROTOCOL)

    for needle in (
        "docs/AUTONOMOUS_FACTORY_POLICY.md",
        "Open a truthful non-draft PR",
        "Never create or convert a draft PR unless Josh explicitly",
        "Never merge.",
        "FINISH WHAT YOU START",
        "OWN AN ISSUE, NOT A PR",
        "NO PLANNING PRS",
        "ONE COHERENT PR BY DEFAULT",
        "Success is measured by issues closed, not pull requests opened.",
        "escalate REVIEW -> FIX",
        "comic-pile-factory-review-claim-v2",
        "comic-pile-factory-fix-claim-v3",
        "comic-pile-factory-fix-progress-v3",
        "comic-pile-factory-ready-v2",
        "age <=2700 seconds",
        "age <=3600 seconds",
        "Lowest GitHub comment ID wins simultaneous races.",
        "A pushed new SHA releases the old-SHA lease automatically.",
    ):
        require(entrypoint, needle, ENTRYPOINT)

    for obsolete in (
        "open a truthful draft PR",
        "mark a draft ready when",
        "merge the pull request",
        "comic-pile-factory-fix-v2:",
        "comic-pile-factory-ready:",
        "HONEST STAGE FAST PATH",
    ):
        forbid(entrypoint, obsolete, ENTRYPOINT)


def main() -> None:
    validate_texts(
        POLICY.read_text(encoding="utf-8"),
        PROTOCOL.read_text(encoding="utf-8"),
        ENTRYPOINT.read_text(encoding="utf-8"),
    )
    print("Autonomous factory policy invariants are aligned.")


if __name__ == "__main__":
    main()
