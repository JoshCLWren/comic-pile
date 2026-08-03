#!/usr/bin/env python3
"""Fail when autonomous factory policy files drift on critical invariants."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "docs" / "AUTONOMOUS_FACTORY_POLICY.md"
PROTOCOL = ROOT / "docs" / "ISSUE_EXECUTION_PROTOCOL.md"
ENTRYPOINT = ROOT / "scripts" / "comic-pile-opencode-factory.sh"


def require(text: str, needle: str, source: Path) -> None:
    """Require one invariant string in a policy source."""
    if needle not in text:
        raise SystemExit(f"{source}: missing required policy text: {needle!r}")


def forbid(text: str, needle: str, source: Path) -> None:
    """Reject one known contradictory policy string."""
    if needle in text:
        raise SystemExit(f"{source}: forbidden policy drift found: {needle!r}")


def validate_texts(policy: str, protocol: str, entrypoint: str) -> None:
    """Validate policy source text against canonical delivery invariants."""
    for needle in (
        "Version: 11",
        "Finish the issue. Do not stop at a commit, PR, review, CI run, or ready marker.",
        "Is there executable work remaining for this owned issue that I can safely do now?",
        "Merely naming remaining work proves the opposite and requires continuing.",
        "One pushed commit, pending CI, green CI, review completion, a large diff, or harder next work are never stop conditions.",
        "Implement the whole issue in one coherent non-draft PR whenever reasonably reviewable.",
        "Never open planning-only, architecture-only, inventory-only, or implementation-plan PRs",
        "Do not start a new issue while an owned issue has executable remaining work.",
        "A merged partial PR does not release the parent issue.",
        "Do not wait passively for broad CI when independent issue work can continue safely",
        "Never push directly to `main`.",
        "Never create or convert a draft PR unless Josh explicitly requests it.",
        "Never merge or enable auto-merge without Josh explicitly ordering that specific merge.",
    ):
        require(policy, needle, POLICY)

    for marker in (
        "comic-pile-factory-implement-claim-v3",
        "comic-pile-factory-implement-progress-v3",
        "comic-pile-factory-review-claim-v2",
        "comic-pile-factory-review-v2:<sha>:pass",
        "comic-pile-factory-review-v2:<sha>:changes-required",
        "comic-pile-factory-fix-claim-v3",
        "comic-pile-factory-fix-progress-v3",
        "comic-pile-factory-ready-v2",
        "comic-pile-factory-needs-human-v2",
        "comic-pile-factory-claim-released-v3",
    ):
        require(policy, marker, POLICY)

    for obsolete in (
        "HONEST STAGE FAST PATH",
        "Planning PRs are encouraged",
        "Always split large PRs into stages",
        "A heartbeat may stop after one substantive commit",
    ):
        forbid(policy, obsolete, POLICY)

    require(protocol, "docs/AUTONOMOUS_FACTORY_POLICY.md", PROTOCOL)
    require(protocol, "Never create a draft pull request unless Josh explicitly requests a draft.", PROTOCOL)
    require(protocol, "Never merge without Josh's explicit authorization", PROTOCOL)

    for needle in (
        "docs/AUTONOMOUS_FACTORY_POLICY.md",
        "Never create or convert a draft PR unless Josh explicitly",
        "Never merge.",
        "FINISH WHAT YOU START",
        "OWN AN ISSUE, NOT A PR",
        "NO PLANNING PRS",
        "ONE COHERENT PR BY DEFAULT",
        "comic-pile-factory-review-claim-v2",
        "comic-pile-factory-fix-claim-v3",
        "comic-pile-factory-ready-v2",
    ):
        require(entrypoint, needle, ENTRYPOINT)

    for obsolete in (
        "open a truthful draft PR",
        "mark a draft ready when",
        "merge the pull request",
        "HONEST STAGE FAST PATH",
    ):
        forbid(entrypoint, obsolete, ENTRYPOINT)


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
