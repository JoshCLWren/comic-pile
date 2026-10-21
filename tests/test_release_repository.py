"""Release ledger layering and repository behavior regression coverage.

The What's New release ledger follows the house layering standard: query
construction and persistence live in ``app/repositories/release_repository.py``
and the service layer owns business rules and transaction boundaries. These
tests keep that boundary from drifting back into the service module.
"""

import ast
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.release import Release
from app.repositories import release_repository

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVICE_MODULE_PATH = REPOSITORY_ROOT / "app" / "services" / "release_ledger.py"
REPOSITORY_MODULE_PATH = REPOSITORY_ROOT / "app" / "repositories" / "release_repository.py"

#: SQLAlchemy names whose import constructs a SQL expression or configures a
#: query. Type-only imports (``AsyncSession``, ``RowMapping``, ...) are not
#: listed.
QUERY_CONSTRUCTION_NAMES = frozenset(
    {
        "and_",
        "case",
        "cast",
        "delete",
        "exists",
        "func",
        "insert",
        "literal",
        "not_",
        "or_",
        "select",
        "selectinload",
        "table",
        "text",
        "tuple_",
        "union",
        "update",
    }
)

#: Session methods that execute a query.
QUERY_EXECUTION_METHODS = frozenset({"execute", "scalars", "scalar", "stream"})

_SESSION_RECEIVER_NAMES = {"conn", "db", "session"}


def _query_construction_imports(source: str) -> set[str]:
    """Return the SQLAlchemy query-construction names imported by one module.

    Args:
        source: Full Python source text of the scanned module.

    Returns:
        The imported names that construct SQL expressions or queries.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "sqlalchemy":
            names.update(
                alias.name for alias in node.names if alias.name in QUERY_CONSTRUCTION_NAMES
            )
    return names


def _session_query_calls(source: str) -> set[str]:
    """Return the session query-execution calls made by one module.

    Args:
        source: Full Python source text of the scanned module.

    Returns:
        The query-execution method names called on a session-like receiver.
    """
    calls: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in QUERY_EXECUTION_METHODS:
            continue
        receiver = node.func.value
        if isinstance(receiver, ast.Name):
            name = receiver.id
        elif isinstance(receiver, ast.Attribute):
            name = receiver.attr
        else:
            name = ""
        if name in _SESSION_RECEIVER_NAMES or name.endswith("session"):
            calls.add(node.func.attr)
    return calls


def test_release_service_builds_no_queries() -> None:
    """The release ledger service must not construct or execute queries itself.

    Args:
        None.

    Returns:
        None.
    """
    source = SERVICE_MODULE_PATH.read_text(encoding="utf-8")

    assert _query_construction_imports(source) == set()
    assert _session_query_calls(source) == set()


def test_release_repository_owns_the_release_queries() -> None:
    """The release repository must own the release-family query construction.

    Args:
        None.

    Returns:
        None.
    """
    source = REPOSITORY_MODULE_PATH.read_text(encoding="utf-8")

    assert "select" in _query_construction_imports(source)
    assert _session_query_calls(source) & {"execute", "scalar"}


@pytest_asyncio.fixture
async def clean_releases(async_db: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Provide a session whose release ledger holds only this test's rows.

    Args:
        async_db: Isolated async database session.

    Yields:
        The same session with an empty release ledger.
    """
    await async_db.execute(text("TRUNCATE TABLE releases CASCADE"))
    yield async_db


async def _add_release(db: AsyncSession, **overrides: object) -> Release:
    """Insert one release row for repository assertions.

    Args:
        db: Async database session.
        overrides: Column values replacing the defaults.

    Returns:
        The persisted release row.
    """
    values: dict[str, object] = {
        "source_repository": "JoshCLWren/comic-pile",
        "source_pr_number": None,
        "source_merge_sha": None,
        "merged_at": None,
        "released_at": datetime(2026, 8, 10, 19, 0, tzinfo=UTC),
        "category": "What's New",
        "title": "Real reader-facing release title",
        "summary": "A real reader-facing release summary for What's New.",
        "body": None,
        "visibility": "public",
        "status": "published",
        "sort_order": 0,
        "provenance_json": {},
    }
    values.update(overrides)
    release = Release(**values)
    await release_repository.add_release(db, release)
    await db.flush()
    return release


@pytest.mark.asyncio
async def test_list_published_releases_hides_malformed_rows(
    clean_releases: AsyncSession,
) -> None:
    """The public list excludes rows whose title repeats their summary.

    Args:
        clean_releases: Async database session with an empty release ledger.

    Returns:
        None.
    """
    visible = await _add_release(clean_releases)
    hidden = await _add_release(
        clean_releases,
        title="persists normalized CBL reading-list sources",
        summary="persists normalized CBL reading-list sources",
    )
    internal = await _add_release(
        clean_releases,
        visibility="internal",
        title="Internal operator release title",
        summary="An internal operator release summary.",
    )

    releases, total = await release_repository.list_published_releases(
        clean_releases, limit=20, offset=0
    )

    assert [release.id for release in releases] == [visible.id]
    assert total == 1
    assert hidden.id not in [release.id for release in releases]
    assert internal.id not in [release.id for release in releases]


@pytest.mark.asyncio
async def test_get_release_for_retraction_reaches_hidden_rows(
    clean_releases: AsyncSession,
) -> None:
    """The retraction lookup reaches rows the public filter hides.

    Args:
        clean_releases: Async database session with an empty release ledger.

    Returns:
        None.
    """
    hidden = await _add_release(
        clean_releases,
        title="makes issue and pull-request",
        summary="makes issue and pull-request",
    )
    await _add_release(clean_releases, status="retracted")

    assert await release_repository.get_published_release(clean_releases, hidden.id) is None

    retraction_target = await release_repository.get_release_for_retraction(
        clean_releases, hidden.id
    )
    assert retraction_target is not None
    assert retraction_target.id == hidden.id


@pytest.mark.asyncio
async def test_find_releases_by_source_requires_a_source_identity(
    clean_releases: AsyncSession,
) -> None:
    """A source lookup without a source identity matches nothing.

    Args:
        clean_releases: Async database session with an empty release ledger.

    Returns:
        None.
    """
    await _add_release(clean_releases, source_pr_number=4242, source_merge_sha="a" * 40)

    assert (
        await release_repository.find_releases_by_source(
            clean_releases,
            source_repository="JoshCLWren/comic-pile",
            source_pr_number=None,
            source_merge_sha=None,
        )
        == []
    )
