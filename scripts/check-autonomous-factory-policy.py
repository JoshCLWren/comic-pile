#!/usr/bin/env python3
"""Fail when autonomous factory policy files drift on critical invariants."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "docs" / "AUTONOMOUS_FACTORY_POLICY.md"
PROTOCOL = ROOT / "docs" / "ISSUE_EXECUTION_PROTOCOL.md"
ENTRYPOINT = ROOT / "scripts" / "comic-pile-opencode-factory.sh"


def require(text: str, needle: str, source: Path) -> None:
    """Require an invariant string in a policy source."""
    if needle not in text:
        raise SystemExit(f"{source}: missing required policy text: {needle!r}")


def forbid(text: str, needle: str, source: Path) -> None:
    """Reject a known contradictory policy string."""
    if needle in text:
        raise SystemExit(f"{source}: forbidden policy drift found: {needle!r}")


def validate_texts(policy: str, protocol: str, entrypoint: str) -> None:
    """Validate policy source text against the canonical delivery invariants."""
    require(policy, "Never push directly to `main`.", POLICY)
    require(
        policy,
        "Never create a draft pull request unless Josh explicitly requests a draft.",
        POLICY,
    )
    require(
        policy,
        "Never merge unless Josh explicitly orders that specific merge.",
        POLICY,
    )
    require(
        policy,
        (
            "All review, repair, and readiness decisions are tied to the exact "
            "pull-request head SHA."
        ),
        POLICY,
    )
    require(policy, "CI-assisted debugging is permitted", POLICY)
    require(
        policy,
        (
            "Labels, claims, comments, verdicts, PR-body edits, and ready markers "
            "do not satisfy this floor by themselves."
        ),
        POLICY,
    )
    require(
        policy,
        (
            "CI failures, rebases, merge conflicts, test updates, review defects, "
            "browser inconvenience, and broad issues are ordinary engineering"
        ),
        POLICY,
    )
    require(
        policy,
        "When strict review finds a bounded, understood defect on a writable branch",
        POLICY,
    )

    canonical_markers = (
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
    )
    for marker in canonical_markers:
        require(policy, marker, POLICY)

    require(policy, "for 45 minutes after its latest claim", POLICY)
    require(policy, "for 60 minutes after its latest claim or progress marker", POLICY)
    require(policy, "An issue implementation lease is active for 60 minutes", POLICY)
    require(policy, "Simultaneous claims are resolved by lowest GitHub comment ID.", POLICY)
    require(policy, "A pushed new SHA releases old-SHA review and repair leases.", POLICY)

    forbid(policy, "comic-pile-factory-fix-v2:", POLICY)
    forbid(policy, "comic-pile-factory-ready:", POLICY)
    forbid(policy, "comic-pile-factory-review-claim:", POLICY)

    require(protocol, "docs/AUTONOMOUS_FACTORY_POLICY.md", PROTOCOL)
    require(
        protocol,
        "Never create a draft pull request unless Josh explicitly requests a draft.",
        PROTOCOL,
    )
    require(
        protocol,
        "Never merge without Josh's explicit authorization",
        PROTOCOL,
    )
    require(
        protocol,
        "run focused local validation that directly exercises the change",
        PROTOCOL,
    )

    require(entrypoint, "docs/AUTONOMOUS_FACTORY_POLICY.md", ENTRYPOINT)
    require(entrypoint, "open a truthful non-draft PR", ENTRYPOINT)
    require(
        entrypoint,
        "Never create or convert a draft PR unless Josh explicitly",
        ENTRYPOINT,
    )
    require(entrypoint, "Never merge.", ENTRYPOINT)
    require(entrypoint, "ONE TARGET, MAXIMUM SAFE PROGRESS", ENTRYPOINT)
    require(entrypoint, "escalate REVIEW -> FIX", ENTRYPOINT)
    require(entrypoint, "comic-pile-factory-review-claim-v2", ENTRYPOINT)
    require(entrypoint, "comic-pile-factory-fix-claim-v3", ENTRYPOINT)
    require(entrypoint, "comic-pile-factory-fix-progress-v3", ENTRYPOINT)
    require(entrypoint, "comic-pile-factory-ready-v2", ENTRYPOINT)
    require(entrypoint, "age <=2700 seconds", ENTRYPOINT)
    require(entrypoint, "age <=3600 seconds", ENTRYPOINT)
    require(entrypoint, "Lowest GitHub comment ID wins simultaneous races.", ENTRYPOINT)
    require(entrypoint, "A pushed new SHA releases the old-SHA lease automatically.", ENTRYPOINT)

    forbid(entrypoint, "open a truthful draft PR", ENTRYPOINT)
    forbid(entrypoint, "mark a draft ready when", ENTRYPOINT)
    forbid(entrypoint, "merge the pull request", ENTRYPOINT)
    forbid(entrypoint, "comic-pile-factory-fix-v2:", ENTRYPOINT)
    forbid(entrypoint, "comic-pile-factory-ready:", ENTRYPOINT)


def main() -> None:
    """Read repository policy sources and validate their alignment."""
    validate_texts(
        POLICY.read_text(encoding="utf-8"),
        PROTOCOL.read_text(encoding="utf-8"),
        ENTRYPOINT.read_text(encoding="utf-8"),
    )
    print("Autonomous factory policy invariants are aligned.")


if __name__ == "__main__":
    main()
