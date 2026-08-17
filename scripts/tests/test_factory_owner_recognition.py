"""Regression tests for shared factory owner-label recognition boundaries.

Issue #1178: shared worker scripts capped owner recognition at factory:16
(``1[0-6]``), so an OmniRoute factory:17 PR was briefly treated as unowned and
adopted by another worker. The boundary must extend through factory:17 without
altering NVIDIA provider/model selection logic.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github" / "scripts"

OWNER_RE_SOURCES = [
    SCRIPTS / "omniroute-factory-worker.sh",
    SCRIPTS / "nvidia-factory-worker.sh",
]

EXPECTED_OWNER_RE = r"^factory:(unowned|local|([1-9]|1[0-7]))$"


def _extract_owner_re(path: Path) -> str:
    """Read the OWNER_RE assignment from a bash worker script."""
    text = path.read_text(encoding="utf-8")
    match = re.search(r"OWNER_RE='([^']+)'", text)
    if not match:
        raise AssertionError(f"{path.name} must define OWNER_RE")
    return match.group(1)


def test_owner_re_extends_through_factory_17() -> None:
    for path in OWNER_RE_SOURCES:
        owner_re = _extract_owner_re(path)
        assert owner_re == EXPECTED_OWNER_RE, (
            f"{path.name} owner boundary must reach factory:17, got {owner_re!r}"
        )


def test_factory_17_recognized_as_owned() -> None:
    pattern = re.compile(EXPECTED_OWNER_RE)
    for label in ["factory:1", "factory:9", "factory:16", "factory:17", "factory:unowned", "factory:local"]:
        assert pattern.fullmatch(label), f"{label} must be a recognized factory owner"


def test_factory_18_and_above_are_out_of_scope() -> None:
    pattern = re.compile(EXPECTED_OWNER_RE)
    for label in ["factory:18", "factory:99", "factory:abc", "factory:"]:
        assert not pattern.fullmatch(label), f"{label} must remain outside the owner boundary"


def test_nvidia_script_keeps_provider_and_model_unchanged() -> None:
    text = (SCRIPTS / "nvidia-factory-worker.sh").read_text(encoding="utf-8")
    assert "OMNIROUTE_MODEL" not in text, "NVIDIA worker must not adopt OmniRoute model handling"
    assert re.search(r"MODEL=\"\$\{2:", text), "NVIDIA worker must keep its positional MODEL argument"
