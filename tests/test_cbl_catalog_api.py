"""Issue #4008: shared CBL catalog folder browsing, search, and pagination.

The catalog is shared source data. These tests prove two brand-new accounts with
zero owned comics receive identical folder trees and search results, that
paging works past the legacy 100-row cap, that inactive lists never leak into
counts, and that read-only requests do not touch ownership or network state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.auth import create_access_token
from app.models import Issue, Thread, User
from app.models.cbl_reference import CBLSource, CBLSourceList
from tests.conftest import get_or_create_user_async

CATALOG_URL = "/api/v1/issue-identity/cbl-sources"


async def _seed_source(
    db: AsyncSession,
    *,
    repository: str = "JoshCLWren/CBL-ReadingLists",
    revision: str = "abc123",
) -> CBLSource:
    source = CBLSource(
        repository=repository,
        revision_sha=revision,
        synced_at=datetime.now(UTC),
    )
    db.add(source)
    await db.flush()
    return source


async def _seed_list(
    db: AsyncSession,
    *,
    source: CBLSource,
    name: str,
    path: str,
    active: bool = True,
    count: int | None = 5,
) -> CBLSourceList:
    row = CBLSourceList(
        source_id=source.id,
        source_path=path,
        name=name,
        declared_issue_count=count,
        content_hash=sha256(f"{name}|{path}".encode()).hexdigest(),
        revision_sha=source.revision_sha,
        active=active,
    )
    db.add(row)
    await db.flush()
    return row


async def _nested_catalog(db: AsyncSession) -> CBLSource:
    """Seed a publisher / nested volume / unsorted catalog with one inactive list."""
    source = await _seed_source(db)
    await _seed_list(
        db,
        source=source,
        name="Mister Miracle 1989",
        path="DC/Mister Miracle (1989)/Mister Miracle.cbl",
    )
    await _seed_list(
        db,
        source=source,
        name="Mister Miracle Annual",
        path="DC/Mister Miracle (1989)/unsorted/Annual.cbl",
    )
    await _seed_list(db, source=source, name="JLI", path="DC/JLI/JLI.cbl")
    await _seed_list(
        db,
        source=source,
        name="Secret Wars",
        path="Marvel/Events/Secret Wars.cbl",
    )
    await _seed_list(
        db,
        source=source,
        name="Secret Wars Crossovers",
        path="Marvel/Events/Tie-ins/Crossovers.cbl",
    )
    await _seed_list(db, source=source, name="Root Reading List", path="Root Reading List.cbl")
    await _seed_list(
        db,
        source=source,
        name="Archived Mister Miracle",
        path="DC/Mister Miracle (1989)/Archived.cbl",
        active=False,
    )
    await _seed_list(
        db,
        source=source,
        name="Archived Only",
        path="Archived Only/Dead.cbl",
        active=False,
    )
    await db.commit()
    return source


async def _second_account_client(client: AsyncClient, db: AsyncSession) -> User:
    """Authenticate the shared test client as a second, zero-collection account."""
    user = await get_or_create_user_async(db, username="cbl_catalog_second_reader")
    token = create_access_token(data={"sub": user.username, "jti": "cbl-catalog-test"})
    client.headers.update({"Authorization": f"Bearer {token}"})
    return user


@pytest.mark.asyncio
async def test_folder_browse_navigates_nested_and_unsorted_folders(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Root -> publisher -> nested volume -> unsorted keeps truthful counts."""
    await _nested_catalog(async_db)

    root = await auth_client.get(f"{CATALOG_URL}/folders")
    assert root.status_code == 200, root.text
    root_body = root.json()
    assert root_body["folder"] == ""
    assert root_body["breadcrumbs"] == [{"name": "All CBLs", "path": ""}]
    assert [folder["name"] for folder in root_body["folders"]] == ["DC", "Marvel"]
    assert root_body["direct_list_count"] == 1
    assert root_body["total_list_count"] == 6
    dc = next(folder for folder in root_body["folders"] if folder["name"] == "DC")
    assert dc == {
        "name": "DC",
        "path": "DC",
        "direct_list_count": 0,
        "total_list_count": 3,
    }

    root_browse = await auth_client.get(f"{CATALOG_URL}/browse")
    assert root_browse.status_code == 200, root_browse.text
    assert [folder["name"] for folder in root_browse.json()["folders"]] == ["DC", "Marvel"]
    assert [item["name"] for item in root_browse.json()["items"]] == ["Root Reading List"]
    assert root_browse.json()["total"] == 1

    publisher = await auth_client.get(f"{CATALOG_URL}/folders", params={"folder": "DC"})
    assert publisher.status_code == 200, publisher.text
    publisher_body = publisher.json()
    assert publisher_body["breadcrumbs"] == [
        {"name": "All CBLs", "path": ""},
        {"name": "DC", "path": "DC"},
    ]
    assert publisher_body["folders"] == [
        {
            "name": "JLI",
            "path": "DC/JLI",
            "direct_list_count": 1,
            "total_list_count": 1,
        },
        {
            "name": "Mister Miracle (1989)",
            "path": "DC/Mister Miracle (1989)",
            "direct_list_count": 1,
            "total_list_count": 2,
        },
    ]

    nested = await auth_client.get(
        f"{CATALOG_URL}/browse",
        params={"folder": "DC/Mister Miracle (1989)"},
    )
    assert nested.status_code == 200, nested.text
    nested_body = nested.json()
    assert nested_body["scope"] == "folder"
    assert [folder["path"] for folder in nested_body["folders"]] == [
        "DC/Mister Miracle (1989)/unsorted"
    ]
    assert [item["name"] for item in nested_body["items"]] == ["Mister Miracle 1989"]
    assert nested_body["breadcrumbs"][-1] == {
        "name": "Mister Miracle (1989)",
        "path": "DC/Mister Miracle (1989)",
    }

    unsorted = await auth_client.get(
        f"{CATALOG_URL}/browse",
        params={"folder": "DC/Mister Miracle (1989)/unsorted"},
    )
    assert unsorted.status_code == 200, unsorted.text
    unsorted_body = unsorted.json()
    assert unsorted_body["folders"] == []
    assert unsorted_body["total"] == 1
    assert [item["name"] for item in unsorted_body["items"]] == ["Mister Miracle Annual"]
    assert unsorted_body["items"][0]["source_repository"] == "JoshCLWren/CBL-ReadingLists"


@pytest.mark.asyncio
async def test_folder_with_trailing_space_round_trips(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A folder path returned with trailing spaces can be followed to its contents."""
    source = await _seed_source(async_db)
    await _seed_list(
        db=async_db,
        source=source,
        name="One",
        path="DC/Events /One.cbl",
    )
    await async_db.commit()

    root = await auth_client.get(f"{CATALOG_URL}/folders")
    assert root.status_code == 200, root.text
    dc = next(folder for folder in root.json()["folders"] if folder["name"] == "DC")

    publisher = await auth_client.get(
        f"{CATALOG_URL}/folders", params={"folder": dc["path"]}
    )
    assert publisher.status_code == 200, publisher.text
    events = next(
        folder for folder in publisher.json()["folders"] if folder["name"] == "Events "
    )
    assert events["path"] == "DC/Events "

    followed = await auth_client.get(
        f"{CATALOG_URL}/browse", params={"folder": events["path"]}
    )
    assert followed.status_code == 200, followed.text
    assert [item["name"] for item in followed.json()["items"]] == ["One"]


@pytest.mark.asyncio
async def test_two_empty_reader_accounts_see_identical_shared_catalog(
    auth_client: AsyncClient,
    client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A zero-collection account sees the same folders, search, and totals."""
    await _nested_catalog(async_db)
    first_user = (await async_db.execute(select(User))).scalars().first()
    assert first_user is not None
    second_user = await _second_account_client(client, async_db)
    assert second_user.id != first_user.id
    assert await async_db.scalar(select(func.count()).select_from(Thread)) == 0
    assert await async_db.scalar(select(func.count()).select_from(Issue)) == 0

    requests = [
        (f"{CATALOG_URL}/folders", {}),
        (f"{CATALOG_URL}/folders", {"folder": "DC/Mister Miracle (1989)"}),
        (f"{CATALOG_URL}/browse", {"folder": "DC"}),
        (f"{CATALOG_URL}/browse", {"q": "mister miracle"}),
        (f"{CATALOG_URL}/browse", {"q": "Secret Wars"}),
    ]
    for url, params in requests:
        first = await auth_client.get(url, params=params)
        second = await client.get(url, params=params)
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json() == second.json(), (url, params)


@pytest.mark.asyncio
async def test_search_and_browse_page_beyond_the_legacy_100_cap(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """150 matching CBLs are all reachable with truthful totals and stable order."""
    source = await _seed_source(async_db)
    expected_names = []
    for index in range(150):
        name = f"Mega Event {index:03d}"
        expected_names.append(name)
        await _seed_list(
            async_db,
            source=source,
            name=name,
            path=f"Mega Publisher/Mega Event {index:03d}.cbl",
        )
    await async_db.commit()

    first = await auth_client.get(
        f"{CATALOG_URL}/browse",
        params={"q": "mega event", "page": 1, "page_size": 100},
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["scope"] == "search"
    assert first_body["total"] == 150
    assert first_body["total_pages"] == 2
    assert first_body["has_next"] is True
    assert first_body["has_previous"] is False
    assert len(first_body["items"]) == 100

    second = await auth_client.get(
        f"{CATALOG_URL}/browse",
        params={"q": "mega event", "page": 2, "page_size": 100},
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["total"] == 150
    assert second_body["has_next"] is False
    assert second_body["has_previous"] is True
    assert len(second_body["items"]) == 50

    combined = [item["name"] for item in first_body["items"] + second_body["items"]]
    assert combined == expected_names
    assert len(set(combined)) == 150

    beyond = await auth_client.get(
        f"{CATALOG_URL}/browse",
        params={"q": "mega event", "page": 3, "page_size": 100},
    )
    assert beyond.status_code == 200, beyond.text
    assert beyond.json()["items"] == []
    assert beyond.json()["total"] == 150

    legacy = await auth_client.get(f"{CATALOG_URL}", params={"q": "mega event", "limit": 100})
    assert legacy.status_code == 200, legacy.text
    assert len(legacy.json()) == 100


@pytest.mark.asyncio
async def test_search_matches_name_and_source_path_case_insensitively(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Search is a shared name/path substring match, independent of folder."""
    await _nested_catalog(async_db)

    by_name = await auth_client.get(f"{CATALOG_URL}/browse", params={"q": "jli"})
    assert by_name.status_code == 200, by_name.text
    assert [item["name"] for item in by_name.json()["items"]] == ["JLI"]
    assert by_name.json()["scope"] == "search"

    by_path = await auth_client.get(f"{CATALOG_URL}/browse", params={"q": "tie-ins"})
    assert by_path.status_code == 200, by_path.text
    assert [item["name"] for item in by_path.json()["items"]] == ["Secret Wars Crossovers"]


@pytest.mark.asyncio
async def test_like_metacharacters_in_folder_and_search_are_literal(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Percent/underscore characters never act as SQL wildcards."""
    source = await _seed_source(async_db)
    await _seed_list(
        db=async_db,
        source=source,
        name="100% Comics",
        path="100% Comics/One Shot.cbl",
    )
    await _seed_list(
        db=async_db,
        source=source,
        name="Under_score",
        path="Under_score/Run.cbl",
    )
    await _seed_list(db=async_db, source=source, name="Other", path="Other/Run.cbl")
    await async_db.commit()

    folder = await auth_client.get(f"{CATALOG_URL}/browse", params={"folder": "100% Comics"})
    assert folder.status_code == 200, folder.text
    assert [item["name"] for item in folder.json()["items"]] == ["100% Comics"]

    search = await auth_client.get(f"{CATALOG_URL}/browse", params={"q": "100%"})
    assert search.status_code == 200, search.text
    assert [item["name"] for item in search.json()["items"]] == ["100% Comics"]

    underscore = await auth_client.get(f"{CATALOG_URL}/browse", params={"q": "Under_score"})
    assert underscore.status_code == 200, underscore.text
    assert [item["name"] for item in underscore.json()["items"]] == ["Under_score"]


@pytest.mark.asyncio
async def test_empty_results_and_explicit_error_envelopes(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Empty searches, empty catalogs, invalid folders, and database outages are explicit."""
    empty_root = await auth_client.get(f"{CATALOG_URL}/folders")
    assert empty_root.status_code == 200, empty_root.text
    assert empty_root.json() == {
        "folder": "",
        "breadcrumbs": [{"name": "All CBLs", "path": ""}],
        "folders": [],
        "direct_list_count": 0,
        "total_list_count": 0,
    }

    empty_search = await auth_client.get(f"{CATALOG_URL}/browse", params={"q": "no such cbl"})
    assert empty_search.status_code == 200, empty_search.text
    assert empty_search.json()["items"] == []
    assert empty_search.json()["total"] == 0
    assert empty_search.json()["total_pages"] == 0

    missing_folder = await auth_client.get(f"{CATALOG_URL}/folders", params={"folder": "DC/Nope"})
    assert missing_folder.status_code == 404, missing_folder.text
    assert missing_folder.json()["detail"]["code"] == "folder_not_found"

    for folder in ("../etc", "DC//JLI", "/DC", "DC/", "DC\\JLI", "DC/./JLI"):
        invalid = await auth_client.get(f"{CATALOG_URL}/folders", params={"folder": folder})
        assert invalid.status_code == 400, (folder, invalid.text)
        assert invalid.json()["detail"]["code"] == "invalid_folder"

    bad_page = await auth_client.get(f"{CATALOG_URL}/browse", params={"page": 0})
    assert bad_page.status_code == 422
    oversized = await auth_client.get(f"{CATALOG_URL}/browse", params={"page_size": 101})
    assert oversized.status_code == 422


@pytest.mark.asyncio
async def test_inactive_lists_are_never_browsable_or_counted(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Archived lists are excluded from items, folders, and recursive totals."""
    await _nested_catalog(async_db)

    archived_folder = await auth_client.get(
        f"{CATALOG_URL}/folders", params={"folder": "DC/Mister Miracle (1989)"}
    )
    assert archived_folder.status_code == 200, archived_folder.text
    assert [item["name"] for item in archived_folder.json()["folders"]] == ["unsorted"]

    archived_only = await auth_client.get(
        f"{CATALOG_URL}/folders", params={"folder": "Archived Only"}
    )
    assert archived_only.status_code == 404, archived_only.text

    search = await auth_client.get(f"{CATALOG_URL}/browse", params={"q": "Archived"})
    assert search.status_code == 200, search.text
    assert search.json()["total"] == 0


@pytest.mark.asyncio
async def test_catalog_requests_are_read_only_and_make_no_github_calls(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Browsing changes no rows and never constructs a GitHub client."""
    import github

    def _no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("CBL catalog reads must not call GitHub")

    monkeypatch.setattr(github, "Github", _no_network)
    source = await _nested_catalog(async_db)
    repository = source.repository
    before_sources = await async_db.scalar(select(func.count()).select_from(CBLSource))
    before_lists = await async_db.scalar(select(func.count()).select_from(CBLSourceList))
    before_users = await async_db.scalar(select(func.count()).select_from(User))
    before_threads = await async_db.scalar(select(func.count()).select_from(Thread))

    for url, params in (
        (f"{CATALOG_URL}/folders", {"folder": "DC"}),
        (f"{CATALOG_URL}/browse", {"folder": "Marvel/Events"}),
        (f"{CATALOG_URL}/browse", {"q": "secret"}),
    ):
        response = await auth_client.get(url, params=params)
        assert response.status_code == 200, response.text

    async_db.expire_all()
    assert await async_db.scalar(select(func.count()).select_from(CBLSource)) == before_sources
    assert await async_db.scalar(select(func.count()).select_from(CBLSourceList)) == before_lists
    assert await async_db.scalar(select(func.count()).select_from(User)) == before_users
    assert await async_db.scalar(select(func.count()).select_from(Thread)) == before_threads
    assert repository == "JoshCLWren/CBL-ReadingLists"


@pytest.mark.asyncio
async def test_folder_prefix_query_uses_the_catalog_prefix_index(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """The folder prefix predicate is served by the active/path index.

    Tests build the schema from ORM metadata, so this also proves the index is
    declared on the model rather than only in the migration.
    """
    await _nested_catalog(async_db)
    await async_db.execute(text("SET LOCAL enable_seqscan = off"))
    plan_rows = (
        (
            await async_db.execute(
                text(
                    "EXPLAIN SELECT id FROM cbl_source_lists "
                    "WHERE active AND source_path LIKE 'DC/%'"
                )
            )
        )
        .scalars()
        .all()
    )
    plan = "\n".join(plan_rows)
    assert "ix_cbl_source_list_active_path" in plan, plan


@pytest.mark.asyncio
async def test_catalog_query_count_is_constant_as_the_catalog_grows(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Folder and search requests issue a fixed number of catalog SELECTs.

    This is the measured half of the acceptance contract: the response never
    fans out per source list or per folder, so a 150-list/2-source catalog costs
    the same as a tiny one.
    """
    first_source = await _seed_source(async_db)
    second_source = await _seed_source(async_db, repository="example/second-cbl", revision="def456")
    for index in range(75):
        for source in (first_source, second_source):
            await _seed_list(
                async_db,
                source=source,
                name=f"Measured Event {index:03d}",
                path=f"Measured/{source.id}/Measured Event {index:03d}.cbl",
            )
    await async_db.commit()

    statements: list[str] = []

    def _capture(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del conn, cursor, parameters, context, executemany
        if "cbl_source_lists" in statement:
            statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        folder_response = await auth_client.get(
            f"{CATALOG_URL}/browse", params={"folder": "Measured"}
        )
        folder_statement_count = len(statements)
        statements.clear()
        search_response = await auth_client.get(
            f"{CATALOG_URL}/browse", params={"q": "measured event", "page_size": 100}
        )
        search_statement_count = len(statements)
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)

    assert folder_response.status_code == 200, folder_response.text
    assert folder_response.json()["total"] == 0
    assert [folder["total_list_count"] for folder in folder_response.json()["folders"]] == [
        75,
        75,
    ]
    assert folder_statement_count <= 4
    assert search_response.status_code == 200, search_response.text
    assert search_response.json()["total"] == 150
    assert search_statement_count <= 2


@pytest.mark.asyncio
async def test_catalog_database_outage_returns_stable_503(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database failure maps to a machine-readable unavailable response."""
    from app.api import cbl_sources

    async def _fail(*args: object, **kwargs: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("database is down"))

    monkeypatch.setattr(cbl_sources, "browse_cbl_catalog", _fail)
    response = await auth_client.get(f"{CATALOG_URL}/browse")
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "cbl_catalog_unavailable"
