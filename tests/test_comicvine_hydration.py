"""Tests for normalized ComicVine metadata persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.comicvine_hydration as hydration
from app.models.external_identity import ExternalIdentity
from app.services.comicvine_fallback import metadata_needs_hydration
from comic_pile.comicvine_provider import ComicVineError, ComicVineResponse


@dataclass
class FakeIdentity:
    """Minimal external identity stand-in for service tests."""

    external_id: str
    metadata_json: dict[str, object]


def test_normalize_issue_preserves_raw_and_relationship_roles() -> None:
    """Issue normalization should retain raw evidence and useful relationship fields."""
    raw: dict[str, object] = {
        "id": 11,
        "name": "The Test",
        "issue_number": "1",
        "cover_date": "2026-01-01",
        "store_date": "2025-12-31",
        "volume": {"id": 22, "name": "Series", "ignored": "value"},
        "image": {"medium_url": "https://img/medium", "small_url": "https://img/small"},
        "person_credits": [{"id": 1, "name": "Writer", "role": "writer", "junk": True}],
        "character_credits": [{"id": 2, "name": "Hero"}],
        "team_credits": [{"id": 3, "name": "Team"}],
        "story_arc_credits": [{"id": 4, "name": "Arc"}],
    }

    normalized = hydration.normalize_issue(raw)

    assert normalized["name"] == "The Test"
    assert normalized["primary_image"] == "https://img/medium"
    assert normalized["volume"] == {"id": 22, "name": "Series"}
    assert normalized["creator_credits"] == [{"id": 1, "name": "Writer", "role": "writer"}]
    assert normalized["story_arcs"] == [{"id": 4, "name": "Arc"}]
    assert normalized["raw_provider_payload"] is raw


def test_normalize_volume_preserves_publisher_and_best_image() -> None:
    """Volume normalization should retain core identity metadata and full raw evidence."""
    raw: dict[str, object] = {
        "id": 22,
        "name": "Series",
        "publisher": {"id": 7, "name": "Publisher"},
        "start_year": "2025",
        "count_of_issues": 12,
        "image": {"original_url": "https://img/original"},
    }

    normalized = hydration.normalize_volume(raw)

    assert normalized["publisher"] == {"id": 7, "name": "Publisher"}
    assert normalized["primary_image"] == "https://img/original"
    assert normalized["raw_provider_payload"] is raw


def test_normalizers_tolerate_provider_shape_oddities() -> None:
    """Unexpected relationship/image shapes should not corrupt normalized metadata."""
    issue = hydration.normalize_issue(
        {
            "image": "unexpected",
            "volume": "unexpected",
            "person_credits": {"id": 1},
            "character_credits": None,
            "team_credits": "unexpected",
            "story_arc_credits": [None, "bad"],
        }
    )
    volume = hydration.normalize_volume({"image": [], "publisher": "unexpected"})

    assert issue["primary_image"] is None
    assert issue["volume"] is None
    assert issue["creator_credits"] == []
    assert issue["story_arcs"] == []
    assert volume["publisher"] is None
    assert volume["primary_image"] is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-08-10T09:00:00Z", "2026-08-10T09:00:00+00:00"),
        ("not-a-date", None),
        (None, None),
    ],
)
def test_provider_timestamp_is_tolerant(value: object, expected: str | None) -> None:
    """Provider timestamps should parse when valid and degrade safely when malformed."""
    parsed = hydration._provider_timestamp(value)
    assert (parsed.isoformat() if parsed else None) == expected


def test_stored_cover_preserves_original_provider_cdn_url() -> None:
    """Keep ComicVine CDN assets unchanged for direct browser rendering."""
    raw: dict[str, object] = {
        "id": 453414,
        "name": "Who Shot the Hulk Part 3",
        "issue_number": "3",
        "volume": {"id": 23834, "name": "Hulk (2014)"},
        "image": {
            "original_url": "https://static.comicvine.com/uploads/original/50/453414_hulk.jpg",
            "super_url": "https://static.comicvine.com/uploads/super/50/453414_hulk.jpg",
            "screen_large_url": (
                "https://static.comicvine.com/uploads/screen_large/50/453414_hulk.jpg"
            ),
            "medium_url": "https://static.comicvine.com/uploads/medium/50/453414_hulk.jpg",
            "small_url": "https://static.comicvine.com/uploads/small/50/453414_hulk.jpg",
            "thumb_url": "https://static.comicvine.com/uploads/thumb/50/453414_hulk.jpg",
            "tiny_url": "https://static.comicvine.com/uploads/tiny/50/453414_hulk.jpg",
            "icon_url": "https://static.comicvine.com/uploads/icon/50/453414_hulk.jpg",
        },
        "person_credits": [{"id": 1001, "name": "Peter David", "role": "writer"}],
    }

    primary_image = hydration.normalize_issue(raw)["primary_image"]

    assert primary_image == "https://static.comicvine.com/uploads/original/50/453414_hulk.jpg"

@pytest.mark.asyncio
async def test_persist_issue_result_uses_provider_independent_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue persistence should upsert a ComicVine issue without touching continuity."""
    observed: dict[str, object] = {}

    async def fake_upsert(db: object, **kwargs: object) -> FakeIdentity:
        observed.update(kwargs)
        return FakeIdentity(str(kwargs["external_id"]), cast(dict[str, object], kwargs["metadata_json"]))

    monkeypatch.setattr(hydration, "upsert_external_identity", fake_upsert)
    raw = {
        "id": 99,
        "name": "Issue",
        "site_detail_url": "https://comicvine/issue/99",
        "date_last_updated": "2026-08-10T09:00:00Z",
    }

    identity = await hydration.persist_issue_result(cast(object, None), raw)

    assert identity.external_id == "99"
    assert observed["provider"] == "comicvine"
    assert observed["entity_type"] == "issue"
    assert observed["external_url"] == "https://comicvine/issue/99"
    assert observed["provider_updated_at"] is not None
    assert observed["metadata_merger"] is hydration.merge_sparse_issue_metadata


@pytest.mark.asyncio
async def test_persist_issue_result_uses_sparse_merger_for_sparse_or_roster_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sparse and roster writes merge; full singular writes stay authoritative."""
    observed: dict[str, object] = {}

    async def fake_upsert(db: object, **kwargs: object) -> FakeIdentity:
        observed.clear()
        observed.update(kwargs)
        return FakeIdentity(str(kwargs["external_id"]), cast(dict[str, object], kwargs["metadata_json"]))

    monkeypatch.setattr(hydration, "upsert_external_identity", fake_upsert)
    sparse = {"id": 99, "issue_number": "5", "volume": {"id": 5162}}

    await hydration.persist_issue_result(cast(object, None), sparse)
    assert observed["metadata_merger"] is hydration.merge_sparse_issue_metadata

    await hydration.persist_issue_result(
        cast(object, None), _deep_issue_result(), roster_row=True
    )
    assert observed["metadata_merger"] is hydration.merge_sparse_issue_metadata

    await hydration.persist_issue_result(cast(object, None), _deep_issue_result())
    assert observed["metadata_merger"] is None


@pytest.mark.asyncio
async def test_persist_volume_result_requires_stable_integer_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider rows without stable IDs must not create guessed identities."""
    with pytest.raises(ComicVineError, match="missing an integer id"):
        await hydration.persist_volume_result(cast(object, None), {"id": "bad"})

    async def fake_upsert(db: object, **kwargs: object) -> FakeIdentity:
        return FakeIdentity(str(kwargs["external_id"]), cast(dict[str, object], kwargs["metadata_json"]))

    monkeypatch.setattr(hydration, "upsert_external_identity", fake_upsert)
    identity = await hydration.persist_volume_result(
        cast(object, None),
        {"id": 5, "name": "Volume", "site_detail_url": "https://comicvine/volume/5"},
    )
    assert identity.external_id == "5"


class FakeClient:
    """Provider-client stand-in that records endpoint hydration requests."""

    def __init__(self, *, issue_from_cache: bool = False) -> None:
        """Configure cache provenance for the returned deep issue fixture.

        Args:
            issue_from_cache: Whether ``fetch_issue`` reports a cached response.
        """
        self.issue_from_cache = issue_from_cache
        self.story_arcs: list[int] = []

    async def fetch_issue(self, issue_id: int, *, refresh: bool = False) -> ComicVineResponse:
        """Return one deep issue fixture."""
        return ComicVineResponse(
            {
                "status_code": 1,
                "results": {
                    "id": issue_id,
                    "story_arc_credits": [
                        {"id": 3, "name": "Arc"},
                        {"id": 3, "name": "Duplicate"},
                        {"id": "bad"},
                    ],
                },
            },
            self.issue_from_cache,
            "issue",
        )

    async def fetch_story_arc(self, arc_id: int, *, refresh: bool = False) -> ComicVineResponse:
        """Record a story-arc request and return an unordered membership fixture."""
        self.story_arcs.append(arc_id)
        return ComicVineResponse(
            {"status_code": 1, "results": {"id": arc_id, "issues": [{"id": 2}, {"id": 1}]}},
            False,
            "arc",
        )

    async def fetch_volume(self, volume_id: int, *, refresh: bool = False) -> ComicVineResponse:
        """Return one volume fixture."""
        return ComicVineResponse(
            {"status_code": 1, "results": {"id": volume_id, "name": "Volume"}},
            False,
            "volume",
        )

    async def fetch_volume_issues(
        self, volume_id: int, *, refresh: bool = False
    ) -> list[dict[str, object]]:
        """Return basic issue rows for one volume."""
        return [
            {"id": 1, "issue_number": "1", "volume": {"id": volume_id}},
            {"id": 2, "issue_number": "2", "volume": {"id": volume_id}},
        ]


@pytest.mark.asyncio
async def test_hydrate_issue_deduplicates_story_arc_fetches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deep hydration should cache each discovered story arc once per issue response."""
    client = FakeClient()

    async def fake_persist(db: object, result: dict[str, object], **kwargs: object) -> FakeIdentity:
        return FakeIdentity(str(result["id"]), result)

    monkeypatch.setattr(hydration, "persist_issue_result", fake_persist)
    identity = await hydration.hydrate_issue(cast(object, None), cast(object, client), 42)

    assert identity.external_id == "42"
    assert client.story_arcs == [3]


@pytest.mark.asyncio
async def test_hydrate_issue_keeps_success_when_story_arc_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A relationship endpoint failure should not erase the successfully hydrated issue."""
    client = FakeClient()

    async def failing_arc(arc_id: int, *, refresh: bool = False) -> ComicVineResponse:
        raise ComicVineError("transient")

    async def fake_persist(db: object, result: dict[str, object], **kwargs: object) -> FakeIdentity:
        return FakeIdentity(str(result["id"]), result)

    monkeypatch.setattr(client, "fetch_story_arc", failing_arc)
    monkeypatch.setattr(hydration, "persist_issue_result", fake_persist)

    identity = await hydration.hydrate_issue(cast(object, None), cast(object, client), 42)

    assert identity.external_id == "42"


@pytest.mark.asyncio
async def test_hydrate_volume_persists_volume_and_complete_roster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Volume hydration should persist the series and every basic issue row idempotently."""
    client = FakeClient()

    async def fake_volume(db: object, result: dict[str, object]) -> FakeIdentity:
        return FakeIdentity(str(result["id"]), result)

    async def fake_issue(
        db: object, result: dict[str, object], *, roster_row: bool = False
    ) -> FakeIdentity:
        return FakeIdentity(str(result["id"]), result)

    monkeypatch.setattr(hydration, "persist_volume_result", fake_volume)
    monkeypatch.setattr(hydration, "persist_issue_result", fake_issue)

    volume, issues = await hydration.hydrate_volume(cast(object, None), cast(object, client), 7)

    assert volume.external_id == "7"
    assert [issue.external_id for issue in issues] == ["1", "2"]


def test_result_object_rejects_collection_shape() -> None:
    """Singular hydration must reject collection-shaped responses."""
    with pytest.raises(ComicVineError, match="object result"):
        hydration._result_object({"results": []})


def _deep_issue_result(**overrides: object) -> dict[str, object]:
    """Return a singular-issue provider row carrying deep relationship evidence."""
    raw: dict[str, object] = {
        "id": 37625,
        "name": "The Deep Title",
        "issue_number": "5",
        "cover_date": "1993-11-01",
        "store_date": "1993-10-01",
        "volume": {"id": 5162, "name": "1963"},
        "image": {"medium_url": "https://img/medium"},
        "person_credits": [{"id": 1, "name": "Writer", "role": "writer"}],
        "character_credits": [{"id": 2, "name": "Hero"}],
        "team_credits": [{"id": 3, "name": "Team"}],
        "story_arc_credits": [{"id": 4, "name": "Arc"}],
        "date_last_updated": "2026-08-10T09:00:00Z",
        "site_detail_url": "https://comicvine/issue/37625",
    }
    raw.update(overrides)
    return raw


def _sparse_roster_row(**overrides: object) -> dict[str, object]:
    """Return a basic volume-roster row without deep relationship evidence."""
    raw: dict[str, object] = {
        "id": 37625,
        "name": "The Deep Title",
        "issue_number": "5",
        "volume": {"id": 5162, "name": "1963"},
        "image": {"medium_url": "https://img/medium"},
        "site_detail_url": "https://comicvine/issue/37625",
        "date_last_updated": "2026-08-10T09:00:00Z",
    }
    raw.update(overrides)
    return raw


def test_sparse_metadata_merger_preserves_deep_evidence() -> None:
    """A sparse roster row must not erase deep credits, arcs, cover, or raw evidence."""
    existing = hydration.normalize_issue(_deep_issue_result())
    incoming = hydration.normalize_issue(
        _sparse_roster_row(name="Roster Title", cover_date="1993-12-01")
    )

    merged = hydration.merge_sparse_issue_metadata(existing, incoming)

    assert merged["creator_credits"] == [{"id": 1, "name": "Writer", "role": "writer"}]
    assert merged["characters"] == [{"id": 2, "name": "Hero"}]
    assert merged["teams"] == [{"id": 3, "name": "Team"}]
    assert merged["story_arcs"] == [{"id": 4, "name": "Arc"}]
    assert merged["primary_image"] == "https://img/medium"
    merged_raw = merged["raw_provider_payload"]
    existing_raw = existing["raw_provider_payload"]
    assert isinstance(merged_raw, dict)
    assert isinstance(existing_raw, dict)
    # Deep relationship evidence survives even though basic roster facts refresh.
    assert merged_raw["person_credits"] == existing_raw["person_credits"]
    assert merged_raw["story_arc_credits"] == existing_raw["story_arc_credits"]
    assert merged_raw["name"] == "Roster Title"
    assert merged_raw["cover_date"] == "1993-12-01"
    # Non-empty roster facts still refresh basic fields.
    assert merged["name"] == "Roster Title"
    assert merged["cover_date"] == "1993-12-01"


def test_sparse_metadata_merger_keeps_deep_image_when_roster_row_omits_it() -> None:
    """Missing roster fields leave stored values untouched instead of nulling them."""
    existing = hydration.normalize_issue(_deep_issue_result())
    sparse_without_image: dict[str, object] = {
        "id": 37625,
        "issue_number": "5",
        "volume": {"id": 5162, "name": "1963"},
    }

    merged = hydration.merge_sparse_issue_metadata(
        existing, hydration.normalize_issue(sparse_without_image)
    )

    assert merged["primary_image"] == "https://img/medium"
    assert merged["cover_date"] == "1993-11-01"
    assert merged["store_date"] == "1993-10-01"


@pytest.mark.asyncio
async def test_roster_import_preserves_deep_issue_metadata(async_db: AsyncSession) -> None:
    """Deep metadata survives a later basic volume-roster import (#4147)."""
    identity = await hydration.persist_issue_result(async_db, _deep_issue_result())
    stored_raw = identity.metadata_json["raw_provider_payload"]
    assert isinstance(stored_raw, dict)

    updated = await hydration.persist_issue_result(
        async_db, _sparse_roster_row(), roster_row=True
    )

    assert updated.id == identity.id
    metadata = updated.metadata_json
    assert metadata["creator_credits"] == [{"id": 1, "name": "Writer", "role": "writer"}]
    assert metadata["characters"] == [{"id": 2, "name": "Hero"}]
    assert metadata["teams"] == [{"id": 3, "name": "Team"}]
    assert metadata["story_arcs"] == [{"id": 4, "name": "Arc"}]
    assert metadata["primary_image"] == "https://img/medium"
    raw_payload = metadata["raw_provider_payload"]
    assert isinstance(raw_payload, dict)
    assert raw_payload["person_credits"] == stored_raw["person_credits"]
    assert raw_payload["story_arc_credits"] == stored_raw["story_arc_credits"]
    assert await async_db.scalar(select(func.count()).select_from(ExternalIdentity)) == 1


@pytest.mark.asyncio
async def test_deep_hydration_records_application_refresh_marker(
    async_db: AsyncSession,
) -> None:
    """A deep payload records when this app fetched it, not ComicVine's edit date."""
    identity = await hydration.persist_issue_result(
        async_db, _deep_issue_result(date_last_updated="2020-01-01T00:00:00Z")
    )

    marker = identity.metadata_json[hydration.DEEP_METADATA_REFRESHED_AT_KEY]
    assert isinstance(marker, str)
    assert marker
    # ComicVine's edit date is six years old, but the deep fetch just happened.
    assert metadata_needs_hydration(identity) is False


@pytest.mark.asyncio
async def test_roster_write_does_not_advance_deep_refresh_marker(
    async_db: AsyncSession,
) -> None:
    """Roster bookkeeping cannot reset the deep-refresh clock (#4147)."""
    identity = await hydration.persist_issue_result(async_db, _deep_issue_result())
    marker = identity.metadata_json[hydration.DEEP_METADATA_REFRESHED_AT_KEY]

    updated = await hydration.persist_issue_result(
        async_db,
        _sparse_roster_row(name="Roster Title", date_last_updated="2027-01-01T09:00:00Z"),
        roster_row=True,
    )

    assert updated.metadata_json[hydration.DEEP_METADATA_REFRESHED_AT_KEY] == marker
    assert updated.metadata_json["creator_credits"] == [
        {"id": 1, "name": "Writer", "role": "writer"}
    ]


def test_sparse_merge_keeps_deep_payload_revision() -> None:
    """A roster row's revision must not replace the deep payload's revision evidence."""
    existing = hydration.normalize_issue(_deep_issue_result())
    incoming = hydration.normalize_issue(
        _sparse_roster_row(name="Roster Title", date_last_updated="2026-10-20T09:00:00Z")
    )

    merged = hydration.merge_sparse_issue_metadata(existing, incoming)

    raw_payload = merged["raw_provider_payload"]
    assert isinstance(raw_payload, dict)
    assert raw_payload["date_last_updated"] == "2026-08-10T09:00:00Z"
    assert raw_payload["name"] == "Roster Title"
    assert merged["creator_credits"] == [{"id": 1, "name": "Writer", "role": "writer"}]


@pytest.mark.asyncio
async def test_legacy_roster_write_keeps_old_deep_credits_stale(
    async_db: AsyncSession,
) -> None:
    """A roster write cannot hide a legacy row's old deep credits from freshness checks."""
    identity = await hydration.persist_issue_result(async_db, _deep_issue_result())
    legacy_metadata = dict(identity.metadata_json)
    legacy_metadata.pop(hydration.DEEP_METADATA_REFRESHED_AT_KEY)
    identity.metadata_json = legacy_metadata
    await async_db.commit()

    updated = await hydration.persist_issue_result(
        async_db,
        _sparse_roster_row(name="Roster Title", date_last_updated="2026-10-20T09:00:00Z"),
        roster_row=True,
    )

    raw_payload = updated.metadata_json["raw_provider_payload"]
    assert isinstance(raw_payload, dict)
    # The deep payload keeps its own revision, so the newer roster revision is
    # still visible as a deep-metadata refresh debt (#4147).
    assert raw_payload["date_last_updated"] == "2026-08-10T09:00:00Z"
    assert updated.metadata_json["creator_credits"] == [
        {"id": 1, "name": "Writer", "role": "writer"}
    ]
    assert metadata_needs_hydration(updated) is True


@pytest.mark.asyncio
async def test_roster_import_preserves_deep_metadata_even_when_roster_is_newer(
    async_db: AsyncSession,
) -> None:
    """A newer sparse provider timestamp still cannot downgrade richer stored evidence."""
    await hydration.persist_issue_result(async_db, _deep_issue_result())

    updated = await hydration.persist_issue_result(
        async_db,
        _sparse_roster_row(date_last_updated="2026-09-01T09:00:00Z"),
        roster_row=True,
    )

    assert updated.metadata_json["creator_credits"] == [
        {"id": 1, "name": "Writer", "role": "writer"}
    ]
    assert updated.metadata_json["story_arcs"] == [{"id": 4, "name": "Arc"}]


@pytest.mark.asyncio
async def test_sparse_roster_identity_is_enriched_by_later_singular_hydration(
    async_db: AsyncSession,
) -> None:
    """A sparse issue can still be enriched by a later singular issue response."""
    sparse = await hydration.persist_issue_result(
        async_db, _sparse_roster_row(), roster_row=True
    )
    assert sparse.metadata_json["creator_credits"] == []

    deep = await hydration.persist_issue_result(async_db, _deep_issue_result())

    assert deep.id == sparse.id
    assert deep.metadata_json["creator_credits"] == [
        {"id": 1, "name": "Writer", "role": "writer"}
    ]
    assert deep.metadata_json["raw_provider_payload"] == _deep_issue_result()


@pytest.mark.asyncio
async def test_repeated_hydration_is_idempotent(async_db: AsyncSession) -> None:
    """Repeated deep and roster hydration converges on the same rich metadata."""
    await hydration.persist_issue_result(async_db, _deep_issue_result())
    expected = (
        await hydration.persist_issue_result(
            async_db, _sparse_roster_row(), roster_row=True
        )
    ).metadata_json

    for _ in range(2):
        repeated = await hydration.persist_issue_result(
            async_db, _sparse_roster_row(), roster_row=True
        )

    assert repeated.metadata_json == expected
    assert repeated.metadata_json["creator_credits"] == [
        {"id": 1, "name": "Writer", "role": "writer"}
    ]
    assert await async_db.scalar(select(func.count()).select_from(ExternalIdentity)) == 1


@pytest.mark.asyncio
async def test_absent_provider_timestamps_do_not_erase_deep_metadata(
    async_db: AsyncSession,
) -> None:
    """Rows without provider timestamps still merge instead of replacing deep metadata."""
    deep: dict[str, object] = _deep_issue_result()
    deep.pop("date_last_updated")
    identity = await hydration.persist_issue_result(async_db, deep)
    assert identity.provider_updated_at is None

    sparse: dict[str, object] = _sparse_roster_row()
    sparse.pop("date_last_updated")
    updated = await hydration.persist_issue_result(async_db, sparse, roster_row=True)

    assert updated.provider_updated_at is None
    assert updated.metadata_json["creator_credits"] == [
        {"id": 1, "name": "Writer", "role": "writer"}
    ]
    assert updated.metadata_json["raw_provider_payload"] == deep


@pytest.mark.asyncio
async def test_genuine_deep_empty_credits_replace_stored_credits(
    async_db: AsyncSession,
) -> None:
    """An explicit empty array from a full singular response is authoritative."""
    await hydration.persist_issue_result(async_db, _deep_issue_result())

    updated = await hydration.persist_issue_result(
        async_db,
        _deep_issue_result(person_credits=[], character_credits=[], team_credits=[]),
    )

    assert updated.metadata_json["creator_credits"] == []
    assert updated.metadata_json["characters"] == []
    assert updated.metadata_json["teams"] == []
    assert updated.metadata_json["raw_provider_payload"] == _deep_issue_result(
        person_credits=[], character_credits=[], team_credits=[]
    )


@pytest.mark.asyncio
async def test_hydrate_volume_roster_does_not_erase_deep_issue(async_db: AsyncSession) -> None:
    """The volume hydration path itself preserves a previously deep-hydrated issue."""
    await hydration.persist_issue_result(
        async_db, _deep_issue_result(id=1, volume={"id": 7, "name": "1963"})
    )

    _volume, issues = await hydration.hydrate_volume(
        async_db, cast(object, FakeClient()), 7
    )

    issue = next(item for item in issues if item.external_id == "1")
    assert issue.metadata_json["creator_credits"] == [
        {"id": 1, "name": "Writer", "role": "writer"}
    ]
    assert issue.metadata_json["story_arcs"] == [{"id": 4, "name": "Arc"}]


@pytest.mark.asyncio
async def test_hydrate_issue_forwards_cache_provenance_to_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hydration must tell persistence when the provider served a cached payload."""
    observed: dict[str, object] = {}

    async def fake_persist(db: object, result: dict[str, object], **kwargs: object) -> FakeIdentity:
        observed.clear()
        observed.update(kwargs)
        return FakeIdentity(str(result["id"]), result)

    monkeypatch.setattr(hydration, "persist_issue_result", fake_persist)

    await hydration.hydrate_issue(
        cast(object, None), cast(object, FakeClient(issue_from_cache=True)), 42
    )
    assert observed["from_cache"] is True

    await hydration.hydrate_issue(cast(object, None), cast(object, FakeClient()), 42)
    assert observed["from_cache"] is False


@pytest.mark.asyncio
async def test_cached_deep_response_keeps_stored_refresh_clock(async_db: AsyncSession) -> None:
    """A cache-served deep payload persists evidence but never moves the clock (#4147)."""
    identity = await hydration.persist_issue_result(async_db, _deep_issue_result())
    marker = identity.metadata_json[hydration.DEEP_METADATA_REFRESHED_AT_KEY]
    assert isinstance(marker, str)

    cached = await hydration.persist_issue_result(
        async_db, _deep_issue_result(name="Cached Title"), from_cache=True
    )

    assert cached.id == identity.id
    assert cached.metadata_json[hydration.DEEP_METADATA_REFRESHED_AT_KEY] == marker
    assert cached.metadata_json["name"] == "Cached Title"
    assert cached.metadata_json["creator_credits"] == [
        {"id": 1, "name": "Writer", "role": "writer"}
    ]
    assert metadata_needs_hydration(cached) is False


@pytest.mark.asyncio
async def test_cached_deep_response_does_not_make_stale_credits_look_fresh(
    async_db: AsyncSession,
) -> None:
    """Old credits served from cache stay stale so the throttle-cleared retry still runs."""
    identity = await hydration.persist_issue_result(
        async_db, _deep_issue_result(date_last_updated="2020-01-01T00:00:00Z")
    )
    stale_metadata = dict(identity.metadata_json)
    stale_metadata[hydration.DEEP_METADATA_REFRESHED_AT_KEY] = "2020-01-01T00:00:00+00:00"
    identity.metadata_json = stale_metadata
    await async_db.commit()
    assert metadata_needs_hydration(identity) is True

    cached = await hydration.persist_issue_result(
        async_db, _deep_issue_result(date_last_updated="2020-01-01T00:00:00Z"), from_cache=True
    )

    assert cached.metadata_json[hydration.DEEP_METADATA_REFRESHED_AT_KEY] == (
        "2020-01-01T00:00:00+00:00"
    )
    assert metadata_needs_hydration(cached) is True


@pytest.mark.asyncio
async def test_cached_deep_response_can_still_enrich_a_sparse_row(async_db: AsyncSession) -> None:
    """A cache-served deep payload still enriches stored sparse evidence."""
    sparse = await hydration.persist_issue_result(
        async_db, _sparse_roster_row(), roster_row=True
    )
    assert sparse.metadata_json["creator_credits"] == []

    cached = await hydration.persist_issue_result(
        async_db, _deep_issue_result(), from_cache=True
    )

    assert cached.id == sparse.id
    assert cached.metadata_json["creator_credits"] == [
        {"id": 1, "name": "Writer", "role": "writer"}
    ]
    assert hydration.DEEP_METADATA_REFRESHED_AT_KEY not in cached.metadata_json
