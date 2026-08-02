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


def main() -> None:
    """Validate the canonical policy, issue protocol, and local entrypoint."""
    policy = POLICY.read_text()
    protocol = PROTOCOL.read_text()
    entrypoint = ENTRYPOINT.read_text()

    require(policy, "Never push directly to `main`.", POLICY)
    require(policy, "Never create a draft pull request unless Josh explicitly requests a draft.", POLICY)
    require(policy, "Never merge unless Josh explicitly orders that specific merge.", POLICY)
    require(policy, "All review, repair, and readiness decisions are tied to the exact pull-request head SHA.", POLICY)
    require(policy, "CI-assisted debugging is permitted", POLICY)

    require(protocol, "docs/AUTONOMOUS_FACTORY_POLICY.md", PROTOCOL)
    require(protocol, "Never create a draft pull request unless Josh explicitly requests a draft.", PROTOCOL)
    require(protocol, "Never merge without Josh's explicit authorization", PROTOCOL)

    require(entrypoint, "docs/AUTONOMOUS_FACTORY_POLICY.md", ENTRYPOINT)
    require(entrypoint, "open a truthful non-draft PR", ENTRYPOINT)
    require(entrypoint, "Never create or convert a draft PR unless Josh explicitly", ENTRYPOINT)
    require(entrypoint, "Never merge.", ENTRYPOINT)

    forbid(entrypoint, "open a truthful draft PR", ENTRYPOINT)
    forbid(entrypoint, "mark a draft ready when", ENTRYPOINT)

    print("Autonomous factory policy invariants are aligned.")


if __name__ == "__main__":
    main()
