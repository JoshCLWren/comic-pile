"""CBL-first identity tests for the ComicVine hydrator."""

from pathlib import Path

from comic_pile.comicvine_hydrator import HydrationTarget, apply_cbl_issue_identities


def _write_cbl(path: Path, *, issue_id: str) -> None:
    """Write one minimal CBL fixture with an embedded ComicVine issue ID."""
    path.write_text(
        (
            "<ReadingList><Name>Fixture</Name><Books>"
            f'<Book Series="X-Men" Number="12" IssueID="{issue_id}" />'
            "</Books></ReadingList>"
        ),
        encoding="utf-8",
    )


async def test_unique_exact_cbl_issue_id_resolves_unmapped_target(tmp_path: Path) -> None:
    """A unique exact title/issue CBL identity fills an otherwise unresolved target."""
    _write_cbl(tmp_path / "x-men.cbl", issue_id="12345")
    targets = [HydrationTarget(10, 4, " X-MEN ", "#12", 12)]

    resolved = await apply_cbl_issue_identities(targets, tmp_path)

    assert resolved[0].comicvine_issue_id == 12345


async def test_conflicting_exact_cbl_issue_ids_remain_unresolved(tmp_path: Path) -> None:
    """Disagreeing CBL embedded IDs never become an arbitrary provider mapping."""
    _write_cbl(tmp_path / "first.cbl", issue_id="12345")
    _write_cbl(tmp_path / "second.cbl", issue_id="67890")
    targets = [HydrationTarget(10, 4, "X-Men", "12", 12)]

    resolved = await apply_cbl_issue_identities(targets, tmp_path)

    assert resolved[0].comicvine_issue_id is None


async def test_confirmed_identity_wins_over_cbl_evidence(tmp_path: Path) -> None:
    """CBL evidence cannot replace an existing confirmed ComicVine issue identity."""
    _write_cbl(tmp_path / "x-men.cbl", issue_id="12345")
    targets = [HydrationTarget(10, 4, "X-Men", "12", 12, 99999)]

    resolved = await apply_cbl_issue_identities(targets, tmp_path)

    assert resolved[0].comicvine_issue_id == 99999
