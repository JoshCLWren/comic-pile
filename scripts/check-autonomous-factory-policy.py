#!/usr/bin/env python3
"""Fail when autonomous factory policy files drift on critical invariants."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "docs/AUTONOMOUS_FACTORY_POLICY.md"
PROTOCOL = ROOT / "docs/ISSUE_EXECUTION_PROTOCOL.md"
ENTRYPOINT = ROOT / "scripts/comic-pile-opencode-factory.sh"
HEARTBEAT_ENTRYPOINT = ROOT / "scripts/comic-pile-opencode-factory-heartbeat.sh"


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
        "Version: 16",
        "Drive the open issue backlog to zero",
        "The newest unclaimed open issue labeled both `user-reported` and `bug`.",
        "The highest-priority unclaimed reproducible E2E-discovered `bug` issue.",
        "When fewer than four substantive implementation PRs are open",
        "At most one implementation worker may own an issue",
        "Existing open PRs are not automatically higher priority than unclaimed issues.",
        "fetch review submissions and all current inline review threads",
        "A worker's own review conclusion does not silently override existing human or bot feedback.",
        "Workers may merge a PR without asking again only after all of these gates are satisfied",
        "the worker supplies the exact expected head SHA",
        "Never enable auto-merge.",
        "when the executable backlog reaches zero, restore and run the full configured end-to-end test coverage",
        "create a GitHub issue for every reproducible defect surfaced by E2E",
        "preserve `user-reported` only for bugs actually reported by a user",
        "Never push directly to `main`.",
        "Never create or convert a draft PR unless Josh explicitly requests a draft.",
    ):
        require(policy, needle, POLICY)

    for marker in (
        "comic-pile-factory-implement-claim-v3",
        "comic-pile-factory-implement-progress-v3",
        "comic-pile-factory-review-claim-v2",
        "comic-pile-factory-review-v2:<sha>:pass",
        "changes-required",
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
        "Do not start a new issue while an owned issue has executable remaining work.",
        "Prefer finishing already-started issues over starting new ones.",
        "ready PR awaiting Josh's explicit merge authorization",
        "Never merge.",
        "Never merge or enable auto-merge without Josh explicitly authorizing that merge.",
    ):
        forbid(policy, obsolete, POLICY)

    require(protocol, "docs/AUTONOMOUS_FACTORY_POLICY.md", PROTOCOL)
    require(protocol, "Never create a draft pull request unless Josh explicitly requests a draft.", PROTOCOL)

    for needle in (
        "docs/AUTONOMOUS_FACTORY_POLICY.md",
        "Drive the open issue backlog to zero",
        "newest unclaimed open issue labeled both `user-reported` and `bug`",
        "reproducible E2E-discovered",
        "fewer than four substantive implementation PRs",
        "fetch all current-SHA review submissions and inline review threads",
        "exact expected head SHA",
        "Never enable auto-merge",
        "restore the full configured E2E matrix",
        "create one GitHub issue per independent reproducible E2E defect",
        "Never create or convert a draft PR unless Josh explicitly",
        "comic-pile-factory-review-claim-v2",
        "comic-pile-factory-fix-claim-v3",
        "comic-pile-factory-ready-v2",
    ):
        require(entrypoint, needle, ENTRYPOINT)

    for obsolete in (
        "open a truthful draft PR",
        "mark a draft ready when",
        "HONEST STAGE FAST PATH",
        "Prefer finishing already-started issues over starting new ones.",
        "Do not start a new issue while an owned issue has executable remaining work.",
        "ready PR awaiting Josh's explicit merge authorization",
        "Never merge.",
        "Never merge or enable auto-merge without Josh explicitly authorizing that merge.",
    ):
        forbid(entrypoint, obsolete, ENTRYPOINT)


def read_entrypoint_text() -> str:
    """Read the orchestration wrapper and the single-heartbeat policy prompt."""
    return "\n".join(
        (
            ENTRYPOINT.read_text(encoding="utf-8"),
            HEARTBEAT_ENTRYPOINT.read_text(encoding="utf-8"),
        )
    )


def main() -> None:
    """Read repository policy sources and validate their alignment."""
    validate_texts(
        POLICY.read_text(encoding="utf-8"),
        PROTOCOL.read_text(encoding="utf-8"),
        read_entrypoint_text(),
    )
    print("Autonomous factory policy invariants are aligned.")


if __name__ == "__main__":
    main()
