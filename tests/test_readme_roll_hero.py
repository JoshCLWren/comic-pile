"""Guard the README Roll hero contract delivered for issue #3883.

The hero is a committed asset plus a README embed and a registered capture script. A static
check keeps the three pieces from drifting apart (for example, deleting the asset while the
README still points at it).
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
HERO = REPO_ROOT / "docs" / "images" / "roll-hero.png"
PROVENANCE = REPO_ROOT / "docs" / "images" / "README.md"
CAPTURE_SCRIPT = REPO_ROOT / "frontend" / "scripts" / "capture-readme-roll-hero.mjs"
PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
LIVE_DEMO_URL = "https://comic-pile.vercel.app"
MAX_HERO_BYTES = 2 * 1024 * 1024


def _readme_lines() -> list[str]:
    """Return the README split into lines.

    Returns:
        Every README line in document order.
    """
    return README.read_text(encoding="utf-8").splitlines()


def _hero_line_index(lines: list[str]) -> int:
    """Return the index of the README line that embeds the Roll hero.

    Args:
        lines: README lines in document order.

    Returns:
        The zero-based index of the hero embed line.
    """
    return next(index for index, line in enumerate(lines) if "docs/images/roll-hero.png" in line)


def test_readme_embeds_the_roll_hero_above_the_first_section() -> None:
    """The hero must appear near the top of the README with meaningful alt text."""
    lines = _readme_lines()
    hero_index = _hero_line_index(lines)
    hero_line = lines[hero_index]

    assert hero_line.startswith("[!["), "the hero must be an image link near the top of the README"
    assert "Roll page" in hero_line, "alt text must describe the Roll UI"
    assert "screenshot" not in hero_line.casefold(), "alt text must not be the word 'screenshot'"
    assert hero_index < next(
        index for index, line in enumerate(lines) if line.startswith("## ")
    ), "the hero must render above the first README section"


def test_readme_puts_the_live_demo_link_next_to_the_hero() -> None:
    """The live demo link must be prominent, not only in the dense link row."""
    lines = _readme_lines()
    hero_index = _hero_line_index(lines)
    hero_block = "\n".join(lines[hero_index : hero_index + 3])

    assert LIVE_DEMO_URL in hero_block
    assert "**" in hero_block, "the live demo call to action must be visually prominent"


def test_roll_hero_asset_is_committed_under_docs_and_within_budget() -> None:
    """The hero image and its provenance must be committed and stay under the 2 MiB budget."""
    assert HERO.is_file(), "docs/images/roll-hero.png must be committed"
    assert HERO.stat().st_size <= MAX_HERO_BYTES
    provenance = PROVENANCE.read_text(encoding="utf-8")
    assert "seed_dev_db.py" in provenance, "provenance must document the seeded demo source"
    assert "no production library" in provenance.casefold()


def test_capture_script_is_registered_for_the_documented_command() -> None:
    """`pnpm run capture:readme-roll` must exist and point at the capture script."""
    scripts = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["scripts"]

    assert scripts["capture:readme-roll"] == "node scripts/capture-readme-roll-hero.mjs"
    assert CAPTURE_SCRIPT.is_file()
