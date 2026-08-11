"""CBL-first identity tests for the ComicVine hydrator."""

from pathlib import Path

from comic_pile.comicvine_hydrator import HydrationTarget, apply_cbl_issue_identities


def _write_cbl(
    path: Path,
    *,
    issue_id: str,
    series: str = "X-Men",
    issue_number: str = "12",
) -> None:
    """Write one minimal CBL fixture with an embedded ComicVine issue ID."""
    path.write_text(
        (
            "<ReadingList><Name>Fixture</Name><Books>"
            f'<Book Series="{series}" Number="{issue_number}" IssueID="{issue_id}" />'
            "</Books></ReadingList>"
        ),
        encoding="utf-8",
    )


async def test_unique_exact_cbl_issue_id_resolves_unmapped_target(tmp_path: Path) -> None:
    """Resolve an unmapped target from one exact CBL identity.

    Args:
        tmp_path: Temporary directory for the CBL fixture.

    Returns:
        None.
    """
    _write_cbl(tmp_path / "x-men.cbl", issue_id="12345")
    targets = [HydrationTarget(10, 4, " X-MEN ", "#12", 12)]

    resolved = await apply_cbl_issue_identities(targets, tmp_path)

    assert resolved[0].comicvine_issue_id == 12345


async def test_conflicting_exact_cbl_issue_ids_remain_unresolved(tmp_path: Path) -> None:
    """Leave conflicting exact CBL identities unresolved.

    Args:
        tmp_path: Temporary directory for the CBL fixtures.

    Returns:
        None.
    """
    _write_cbl(tmp_path / "first.cbl", issue_id="12345")
    _write_cbl(tmp_path / "second.cbl", issue_id="67890")
    targets = [HydrationTarget(10, 4, "X-Men", "12", 12)]

    resolved = await apply_cbl_issue_identities(targets, tmp_path)

    assert resolved[0].comicvine_issue_id is None


async def test_confirmed_identity_wins_over_cbl_evidence(tmp_path: Path) -> None:
    """Preserve a confirmed identity over conflicting CBL evidence.

    Args:
        tmp_path: Temporary directory for the CBL fixture.

    Returns:
        None.
    """
    _write_cbl(tmp_path / "x-men.cbl", issue_id="12345")
    targets = [HydrationTarget(10, 4, "X-Men", "12", 12, 99999)]

    resolved = await apply_cbl_issue_identities(targets, tmp_path)

    assert resolved[0].comicvine_issue_id == 99999


async def test_empty_normalized_cbl_key_cannot_resolve_blank_target(tmp_path: Path) -> None:
    """Reject malformed CBL evidence whose normalized identity key is empty.

    Args:
        tmp_path: Temporary directory for the CBL fixture.

    Returns:
        None.
    """
    _write_cbl(
        tmp_path / "malformed.cbl",
        issue_id="12345",
        series="#",
        issue_number="#",
    )
    targets = [HydrationTarget(10, 4, "", "", 12)]

    resolved = await apply_cbl_issue_identities(targets, tmp_path)

    assert resolved[0].comicvine_issue_id is None
