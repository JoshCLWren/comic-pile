"""Verify the repository-settings acceptance criteria recorded in issue #3887.

Issue #3887 asks for three observable repository facts: Discussions enabled, a
1280x640 social preview rendered by GitHub, and unchanged repository
topics/description. Two of those are readable through the GitHub API and the
repository page; the displayed social preview additionally requires a
repository-owner upload that no code path can perform. This module freezes the
"unchanged" baseline, evaluates observed state through injectable inputs, and
keeps every network call in ``main`` so the evaluation used by tests stays
deterministic and offline.

The verifier is strictly read-only: it only issues GitHub read requests and
never mutates repository settings, topics, description, or Discussions.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

EXPECTED_REPOSITORY = "JoshCLWren/comic-pile"
PREVIEW_WIDTH = 1280
PREVIEW_HEIGHT = 640
BASELINE_DESCRIPTION = (
    "A dice-driven comic-book reading tracker that helps you choose what to read next."
)
BASELINE_TOPICS: tuple[str, ...] = (
    "comic-books",
    "comic-tracker",
    "comics",
    "dice-roller",
    "fastapi",
    "postgresql",
    "random-picker",
    "react",
    "reading-list",
    "reading-tracker",
    "tbr",
    "typescript",
)
OWNER_ACTION = (
    "Owner action pending: upload docs/images/social-preview.png under "
    "Settings -> General -> Social preview and confirm GitHub renders 1280x640."
)
OG_IMAGE_RE = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"')
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class SocialImage:
    """The social-preview image observable from a repository page.

    Attributes:
        url: ``og:image`` URL served by the repository page.
        width: Pixel width parsed from the image header, or None when unknown.
        height: Pixel height parsed from the image header, or None when unknown.
    """

    url: str
    width: int | None
    height: int | None


@dataclass(frozen=True)
class Criterion:
    """One issue #3887 acceptance fact and the evidence used to judge it.

    Attributes:
        name: Stable criterion identifier.
        passed: Whether the observed state satisfies the criterion.
        evidence: Human-readable observation and, when relevant, next action.
        owner_action: Whether a repository-admin action is still required.
    """

    name: str
    passed: bool
    evidence: str
    owner_action: bool = False


def _topic_list(repo: dict[str, object]) -> tuple[str, ...]:
    """Return repository topics as a stable tuple.

    Args:
        repo: GitHub repository metadata.

    Returns:
        Topic names in their returned order, or an empty tuple when unavailable.
    """
    raw = repo.get("topics")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str))


def evaluate_repo_state(
    repo: dict[str, object], image: SocialImage | None
) -> tuple[Criterion, ...]:
    """Evaluate the issue #3887 acceptance criteria against observed state.

    Args:
        repo: Repository metadata from ``gh api repos/<owner>/<repo>``.
        image: Observed ``og:image`` with parsed dimensions, or None when absent.

    Returns:
        One Criterion per acceptance fact, in a stable order.
    """
    discussions_enabled = repo.get("has_discussions") is True
    discussions = Criterion(
        name="discussions_enabled",
        passed=discussions_enabled,
        evidence=(
            "has_discussions=true"
            if discussions_enabled
            else "has_discussions is not true; owner must enable Discussions"
        ),
        owner_action=not discussions_enabled,
    )

    topics = _topic_list(repo)
    topics_unchanged = sorted(topics) == sorted(BASELINE_TOPICS)
    missing = sorted(set(BASELINE_TOPICS) - set(topics))
    extra = sorted(set(topics) - set(BASELINE_TOPICS))
    topics_criterion = Criterion(
        name="topics_unchanged",
        passed=topics_unchanged,
        evidence=(
            "topics match the #3887 frozen baseline"
            if topics_unchanged
            else f"topics changed; missing={missing}, extra={extra}"
        ),
    )

    description = repo.get("description")
    description_unchanged = description == BASELINE_DESCRIPTION
    description_criterion = Criterion(
        name="description_unchanged",
        passed=description_unchanged,
        evidence=(
            "description matches the #3887 frozen baseline"
            if description_unchanged
            else f"description changed; observed={description!r}"
        ),
    )

    displayed = image is not None and (image.width, image.height) == (
        PREVIEW_WIDTH,
        PREVIEW_HEIGHT,
    )
    observed_size = "none" if image is None else f"{image.width}x{image.height}"
    image_evidence = f"og:image={image.url if image is not None else 'none'} ({observed_size})"
    image_evidence += (
        "; approved 1280x640 preview is displayed"
        if displayed
        else f"; {OWNER_ACTION}"
    )
    social_preview = Criterion(
        name="social_preview_displayed_at_1280x640",
        passed=displayed,
        evidence=image_evidence,
        owner_action=not displayed,
    )

    return (discussions, social_preview, topics_criterion, description_criterion)


def render_report(
    repository: str, criteria: tuple[Criterion, ...]
) -> dict[str, object]:
    """Build the JSON-serializable acceptance report.

    Args:
        repository: Repository slug the criteria were evaluated for.
        criteria: Evaluated acceptance criteria.

    Returns:
        A report containing overall status and per-criterion evidence.
    """
    pending = [criterion.name for criterion in criteria if not criterion.passed]
    return {
        "repository": repository,
        "issue": 3887,
        "verified": not pending,
        "pending": pending,
        "criteria": [asdict(criterion) for criterion in criteria],
    }


def _load_repo(repository: str) -> dict[str, object]:
    """Fetch repository metadata with the read-only GitHub CLI.

    Args:
        repository: ``owner/name`` repository slug.

    Returns:
        Parsed repository metadata.

    Raises:
        RuntimeError: When the CLI returns a payload that is not an object.
    """
    result = subprocess.run(
        ["gh", "api", f"repos/{repository}"],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(f"gh api repos/{repository} did not return an object")
    return payload


def _fetch_og_image(repository: str) -> SocialImage | None:
    """Read a repository page's ``og:image`` and parse PNG dimensions.

    Args:
        repository: ``owner/name`` repository slug.

    Returns:
        The observed social image, or None when the page has no ``og:image``.
    """
    with urllib.request.urlopen(f"https://github.com/{repository}", timeout=30) as response:
        page = response.read().decode("utf-8", errors="replace")
    match = OG_IMAGE_RE.search(page)
    if match is None:
        return None
    url = match.group(1)
    with urllib.request.urlopen(url, timeout=30) as response:
        header = response.read(24)
    width: int | None = None
    height: int | None = None
    if header[:8] == PNG_SIGNATURE and len(header) >= 24:
        width, height = struct.unpack(">II", header[16:24])
    return SocialImage(url=url, width=width, height=height)


def main(argv: list[str] | None = None) -> int:
    """Run the read-only acceptance verifier.

    Args:
        argv: Optional CLI arguments; defaults to ``sys.argv[1:]``.

    Returns:
        Exit status 0 when every criterion passes, or 1 in strict mode when an
        owner action still remains. Report mode always exits 0 so pending owner
        actions are recorded without failing an evidence-gathering job.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository", default=EXPECTED_REPOSITORY)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero while any acceptance criterion is unverified",
    )
    args = parser.parse_args(argv)

    criteria = evaluate_repo_state(_load_repo(args.repository), _fetch_og_image(args.repository))
    print(json.dumps(render_report(args.repository, criteria), indent=2))
    if args.strict and not all(criterion.passed for criterion in criteria):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
