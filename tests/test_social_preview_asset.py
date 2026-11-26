"""Guard the repository social-preview asset delivered for issue #3887.

The image is an owner-upload artifact, so the code-level contract is that the
committed PNG is exactly 1280x640, stays within the image budget, and is built
only from verified repository assets: the real favicon logo and the seeded/demo
Roll capture. The provenance note keeps the remaining owner actions explicit,
and the docs workflow must actually execute this guard in CI.
"""

from __future__ import annotations

import struct
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PREVIEW = REPO_ROOT / "docs" / "images" / "social-preview.png"
SOURCE = REPO_ROOT / "docs" / "images" / "social-preview.html"
HERO = REPO_ROOT / "docs" / "images" / "roll-hero.png"
FAVICON = REPO_ROOT / "static" / "favicon.svg"
PROVENANCE = REPO_ROOT / "docs" / "images" / "README.md"
DOCS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docs.yml"
EXPECTED_WIDTH = 1280
EXPECTED_HEIGHT = 640
MAX_PREVIEW_BYTES = 2 * 1024 * 1024
LOGO_SHAPES = (
    'fill="#0f766e"',
    'cx="16" cy="16" r="4"',
    'cx="8" cy="8" r="2.5"',
    'cx="24" cy="8" r="2.5"',
    'cx="8" cy="24" r="2.5"',
    'cx="24" cy="24" r="2.5"',
)


def _png_dimensions(path: Path) -> tuple[int, int]:
    """Read the width and height from a PNG header without image dependencies.

    Args:
        path: PNG file whose IHDR dimensions are needed.

    Returns:
        The ``(width, height)`` pair stored in the PNG header.
    """
    with path.open("rb") as handle:
        header = handle.read(24)
    assert header[:8] == b"\x89PNG\r\n\x1a\n", "social preview must be a PNG"
    width, height = struct.unpack(">II", header[16:24])
    return width, height


def test_social_preview_is_exactly_1280_by_640_within_budget() -> None:
    """The asset must meet GitHub's social preview size and stay under 2 MiB."""
    assert PREVIEW.is_file(), "docs/images/social-preview.png must be committed"
    assert _png_dimensions(PREVIEW) == (EXPECTED_WIDTH, EXPECTED_HEIGHT)
    assert PREVIEW.stat().st_size <= MAX_PREVIEW_BYTES


def test_social_preview_uses_only_verified_repository_assets() -> None:
    """The render source must use the real logo and the demo Roll capture."""
    source = SOURCE.read_text(encoding="utf-8")
    favicon = FAVICON.read_text(encoding="utf-8")
    assert HERO.is_file(), "the verified Roll hero capture must exist"

    for shape in LOGO_SHAPES:
        assert shape in favicon, f"favicon.svg no longer contains {shape}"
        assert shape in source, f"social preview must use the real logo shape {shape}"

    assert "roll-hero.png" in source, "the demo Roll capture must be the only UI source"
    assert source.count("<img") == 1, "no extra UI capture may be introduced"


def test_render_source_is_reproducible_at_1280_by_640() -> None:
    """The HTML source must document a deterministic, same-size render command."""
    source = SOURCE.read_text(encoding="utf-8")
    assert "--window-size=1280,640" in source, "render command must pin the output size"
    assert "--screenshot=docs/images/social-preview.png" in source, (
        "render command must target the committed asset"
    )
    assert "--force-device-scale-factor=1" in source, "render must not scale by DPI"
    assert 'src="roll-hero.png"' in source, "the captured image must be a repo-relative asset"


def test_provenance_records_demo_only_source_and_owner_actions() -> None:
    """The provenance note must state demo-only data and the remaining admin steps."""
    provenance = PROVENANCE.read_text(encoding="utf-8")
    preview_section = provenance.split("## `social-preview.png`", 1)[1]

    assert "seeded/demo" in preview_section.casefold()
    assert "no personal reading library" in preview_section.casefold()
    assert "Social preview" in preview_section
    assert "Discussions" in preview_section
    assert "topics" in preview_section.casefold()


def test_provenance_does_not_claim_false_issue_closure() -> None:
    """The asset is an intermediate deliverable; only the owner can close #3887."""
    provenance = PROVENANCE.read_text(encoding="utf-8")
    for keyword in ("Closes #3887", "Fixes #3887", "Resolves #3887"):
        assert keyword not in provenance, f"{keyword} would falsely close an admin-only issue"


def test_asset_guard_is_invoked_by_ci() -> None:
    """The docs workflow must run this guard, not merely list it in path filters."""
    workflow = DOCS_WORKFLOW.read_text(encoding="utf-8")
    pytest_steps = [line for line in workflow.splitlines() if "python -m pytest" in line]
    assert pytest_steps, "docs.yml must contain a pytest step"
    assert any(
        "tests/test_social_preview_asset.py" in line for line in pytest_steps
    ), "the social-preview guard must be invoked by CI so the assertions actually run"
    assert workflow.count("tests/test_social_preview_asset.py") >= 2, (
        "the workflow path filter must trigger when only the asset guard changes"
    )
