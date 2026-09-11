from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    content = target.read_text()
    if old not in content:
        raise RuntimeError(f"{path}: expected text not found: {old!r}")
    target.write_text(content.replace(old, new))


replace(
    "app/services/continuity_graph.py",
    "from app.schemas.continuity_readiness import (\n    ContinuityBlocker,\n    UnreadIssueDetail,\n)",
    "from app.schemas.continuity_blocking import ContinuityBlocker, UnreadIssueDetail",
)
replace(
    "app/services/continuity_graph.py",
    'SNAPSHOT_SESSION_KEY = "continuity_readiness_snapshot"',
    'SNAPSHOT_SESSION_KEY = "continuity_graph_snapshot"',
)
replace(
    "app/continuity_chains.py",
    "from app.schemas.continuity_readiness import ContinuityBlocker, ContinuityReadinessNodeType",
    "from app.schemas.continuity_blocking import ContinuityBlocker, ContinuityTargetNodeType",
)
replace(
    "app/continuity_chains.py",
    "node_type: ContinuityReadinessNodeType",
    "node_type: ContinuityTargetNodeType",
)
replace(
    "app/schemas/roll.py",
    "from app.schemas.continuity_readiness import ContinuityBlocker",
    "from app.schemas.continuity_blocking import ContinuityBlocker",
)
replace(
    "tests/test_roll_recovery.py",
    "from app.schemas.continuity_readiness import ContinuityBlocker",
    "from app.schemas.continuity_blocking import ContinuityBlocker",
)

print("Relocated shared continuity blocker types")
