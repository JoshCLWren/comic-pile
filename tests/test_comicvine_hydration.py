"""Tests for normalized ComicVine metadata persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest

import app.comicvine_hydration as hydration
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

    def __init__(self) -> None:
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
            False,
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

    async def fake_persist(db: object, result: dict[str, object]) -> FakeIdentity:
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

    async def fake_persist(db: object, result: dict[str, object]) -> FakeIdentity:
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

    async def fake_issue(db: object, result: dict[str, object]) -> FakeIdentity:
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
