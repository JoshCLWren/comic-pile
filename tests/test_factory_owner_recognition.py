"""Regression coverage for shared factory owner-label recognition boundaries.

Issue #1178: the shared NVIDIA and OmniRoute worker scripts capped owner
recognition at ``factory:17`` (``1[0-6]``), so a factory:17 PR could be treated
as unowned and briefly adopted by another worker. The boundary must extend
through ``factory:17`` without altering NVIDIA provider/model behavior.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"

EXPECTED_OWNER_RE = r"^factory:(unowned|local|([1-9]|1[0-7]))$"

OWNER_RE_SCRIPTS = (
    SCRIPTS / "omniroute-factory-worker.sh",
    SCRIPTS / "nvidia-factory-worker.sh",
)


def _extract_owner_re(path: Path) -> str:
    """Read the OWNER_RE assignment from a bash worker script.

    Args:
        path: The worker script to inspect.

    Returns:
        The OWNER_RE pattern string.
    """
    text = path.read_text(encoding="utf-8")
    match = re.search(r"OWNER_RE='([^']+)'", text)
    assert match is not None, f"{path.name} must define OWNER_RE"
    return match.group(1)


def test_shared_owner_re_extends_through_factory_17() -> None:
    """Every shared worker must recognize owners through factory:17."""
    for path in OWNER_RE_SCRIPTS:
        owner_re = _extract_owner_re(path)
        assert owner_re == EXPECTED_OWNER_RE, (
            f"{path.name} owner boundary must reach factory:17, got {owner_re!r}"
        )


def test_factory_17_is_recognized_as_owned() -> None:
    """factory:17 must never be treated as unowned by the shared workers."""
    pattern = re.compile(EXPECTED_OWNER_RE)
    for label in (
        "factory:1",
        "factory:9",
        "factory:17",
        "factory:17",
        "factory:unowned",
        "factory:local",
    ):
        assert pattern.fullmatch(label), f"{label} must be a recognized factory owner"


def test_factory_18_and_above_remain_out_of_scope() -> None:
    """The recognition boundary stops at factory:17, not factory:18+."""
    pattern = re.compile(EXPECTED_OWNER_RE)
    for label in ("factory:18", "factory:19", "factory:99", "factory:abc", "factory:"):
        assert not pattern.fullmatch(label), (
            f"{label} must remain outside the shared owner boundary"
        )


def test_nvidia_worker_keeps_provider_and_model_behavior() -> None:
    """The NVIDIA worker must retain its positional model contract and probe."""
    text = (SCRIPTS / "nvidia-factory-worker.sh").read_text(encoding="utf-8")
    assert 'MODEL="${2:?model required}"' in text, (
        "NVIDIA worker must keep its positional MODEL argument"
    )
    assert "FCM_NVIDIA_MODEL_OK" in text, (
        "NVIDIA worker must keep its NVIDIA model probe"
    )
    assert "OMNIROUTE_MODEL" not in text, (
        "NVIDIA worker must not adopt OmniRoute model handling"
    )


def test_omniroute_worker_keeps_runtime_model_contract() -> None:
    """The OmniRoute worker must retain its environment model contract."""
    text = (SCRIPTS / "omniroute-factory-worker.sh").read_text(encoding="utf-8")
    assert 'MODEL="${OMNIROUTE_MODEL:?OMNIROUTE_MODEL is required}"' in text