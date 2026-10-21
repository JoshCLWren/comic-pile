"""Regression coverage for Alembic revision graph integrity."""

from pathlib import Path

from alembic.config import Config
from alembic.script import Script, ScriptDirectory

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _script_directory() -> ScriptDirectory:
    """Load the repository's Alembic revision map without a database."""
    config = Config(REPOSITORY_ROOT / "alembic.ini")
    return ScriptDirectory.from_config(config)


def _is_ancestor(script: ScriptDirectory, candidate: str, start: str) -> bool:
    """Return whether ``candidate`` is reachable as an ancestor of ``start``."""
    stack: list[str | None] = [start]
    seen: set[str] = set()

    while stack:
        current = stack.pop()
        if current == candidate:
            return True
        if current is None or current in seen:
            continue
        seen.add(current)
        revision = script.revision_map.get_revision(current)
        if revision is None:
            continue
        down = revision.down_revision
        if isinstance(down, str):
            stack.append(down)
        else:
            stack.extend(down or ())

    return False


def _down_revisions(revision: Script) -> tuple[str, ...]:
    """Return the parent revision ids declared by ``revision``."""
    down = revision.down_revision
    if isinstance(down, str):
        return (down,)
    return tuple(down or ())


def _children(script: ScriptDirectory, parent: str) -> list[str]:
    """Return the revisions that declare ``parent`` as a down revision."""
    return [
        revision.revision
        for revision in script.walk_revisions()
        if parent in _down_revisions(revision)
    ]


def test_migration_history_has_a_single_head() -> None:
    """The migration history must end at exactly one Alembic head."""
    heads = _script_directory().get_heads()

    assert len(heads) == 1, f"Expected one Alembic head, found {heads}"


def test_queue_position_is_manual_migration_extends_the_head() -> None:
    """The #3638 column migration must extend the head, never fork off one.

    ``q4m500000001`` pointed at the interior revision ``n6e300000001``,
    which already had a child (``e913be4e091d``). That fork left the
    repository with two Alembic heads, so ``alembic upgrade head`` failed on
    deployment. The parent must stay a leaf of the older graph.
    """
    script = _script_directory()
    revision = script.get_revision("q4m500000001")

    assert revision is not None
    assert revision.down_revision == "c36800000001"
    assert _children(script, "c36800000001") == ["q4m500000001"]


def test_merge_revisions_list_only_independent_heads() -> None:
    """No merge may list a down revision that another entry already contains.

    Redundant ancestors inside a multi-revision ``down_revision`` tuple crash
    Alembic's head maintainer with ``KeyError`` while replaying history.
    """
    script = _script_directory()
    violations: list[str] = []

    for revision in script.walk_revisions():
        down = revision.down_revision
        if not isinstance(down, tuple):
            continue
        for entry in down:
            for other in down:
                if entry != other and _is_ancestor(script, entry, other):
                    message = (
                        f"{revision.revision}: down entry {entry!r} is an "
                        f"ancestor of {other!r}"
                    )
                    violations.append(message)

    assert violations == [], "Redundant merge ancestors found:" + "".join(
        f"\n - {violation}" for violation in violations
    )


def test_cbl_adoption_receipts_follow_cutover_head() -> None:
    """Receipts stay a child of ``c25530000001`` after #3495 patches that revision.

    #3495 edits the Roll cutover upgrade in place and keeps the same
    revision id. Pointing this child at a new id would fork the graph
    once that patch lands; pointing it at the pre-cutover parent would
    create two heads.
    """
    revision = _script_directory().get_revision("n7c4a1000001")
    assert revision is not None
    assert revision.down_revision == "c25530000001"
    cutover = _script_directory().get_revision("c25530000001")
    assert cutover is not None
    assert cutover.down_revision == "m5d300000001"


def test_every_down_revision_resolves() -> None:
    """Every referenced down revision must exist in the revision map."""
    script = _script_directory()
    known = {revision.revision for revision in script.walk_revisions()}

    for revision in script.walk_revisions():
        down = revision.down_revision
        entries: list[str] = (
            [down] if isinstance(down, str) else list(down) if down is not None else []
        )
        for entry in entries:
            assert entry in known, (
                f"{revision.revision} references missing down revision {entry!r}"
            )
