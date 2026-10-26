"""Queue series metadata projection coverage for issue #3605.

Queue rows carry confirmed year, run/volume label, and publisher from each
reader-owned thread's own confirmed provider series identity. These tests pin
the extraction rules (truthful values only, no fabricated volume numbers, no
cross-identity mixing) and the per-row isolation when two threads share a
display title.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.services.thread_service import _extract_series_metadata, list_queue_threads
from tests.conftest import get_or_create_user_async


def test_extracts_verified_year_run_label_and_publisher() -> None:
    """A confirmed identity contributes its own stored year, run, publisher."""
    docs = [
        {
            "start_year": "2013",
            "name": "Uncanny X-Men",
            "publisher": {"name": "Marvel"},
        }
    ]

    year, volume, publisher = _extract_series_metadata(docs, thread_title="X-Men")

    assert year == 2013
    assert volume == "Uncanny X-Men"
    assert publisher == "Marvel"


@pytest.mark.parametrize(
    ("metadata", "expected_year"),
    [
        ({"start_year": "1999"}, 1999),
        ({"start_year": 1999}, 1999),
        ({"cover_date": "2013-05-01"}, 2013),
        ({"start_year": "unknown"}, None),
        ({"start_year": 12}, None),
        ({"start_year": True}, None),
    ],
)
def test_publication_year_only_comes_from_plausible_stored_values(
    metadata: dict[str, object],
    expected_year: int | None,
) -> None:
    """String, numeric, and publication-date years are accepted; junk is not."""
    year, _volume, _publisher = _extract_series_metadata(
        [metadata], thread_title="Some Series"
    )

    assert year == expected_year


def test_title_matching_volume_name_is_not_relabelled_as_a_run() -> None:
    """A provider name equal to the title never becomes a fabricated volume label."""
    docs = [{"start_year": 2013, "name": "Uncanny X-Men"}]

    _year, volume, _publisher = _extract_series_metadata(docs, thread_title="Uncanny X-Men")

    assert volume is None


def test_fields_are_never_combined_across_two_confirmed_identities() -> None:
    """Only the canonical identity document is read, so rows never mix series."""
    docs = [
        {"start_year": 2013, "publisher": {"name": "Marvel"}},
        {"name": "Some Other Run", "publisher": {"name": "DC Comics"}},
    ]

    year, volume, publisher = _extract_series_metadata(docs, thread_title="Uncanny X-Men")

    assert year == 2013
    assert volume is None
    assert publisher == "Marvel"


def test_absent_documents_project_no_identity() -> None:
    """An unmapped thread has no metadata document and projects no identity."""
    assert _extract_series_metadata([], thread_title="Unmapped") == (None, None, None)


async def _add_thread(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
) -> Thread:
    """Insert one active Queue thread and return it.

    Args:
        db: Database session.
        user_id: Owning reader.
        title: Display title (may repeat across distinct threads).
        queue_position: Queue order for the row.

    Returns:
        The flushed thread with its database id.
    """
    thread = Thread(
        user_id=user_id,
        title=title,
        format="Comic",
        issues_remaining=5,
        queue_position=queue_position,
        status="active",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    return thread


async def _add_series_identity(
    db: AsyncSession,
    *,
    thread: Thread,
    external_id: str,
    metadata: dict[str, object],
    status: str = "confirmed",
    confidence: float | None = 1.0,
) -> None:
    """Attach one provider series identity to a thread.

    Args:
        db: Database session.
        thread: Reader-owned thread receiving the mapping.
        external_id: Provider identity id (test-unique).
        metadata: Stored provider series metadata document.
        status: Mapping status; ``confirmed`` participates in Queue display.
        confidence: Mapping confidence used for canonical identity ordering.
    """
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id=external_id,
        metadata_json=metadata,
    )
    db.add(identity)
    await db.flush()
    db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id,
            external_identity_id=identity.id,
            status=status,
            confidence=confidence,
        )
    )


@pytest.mark.asyncio
async def test_same_titled_rows_project_their_own_confirmed_metadata(
    async_db: AsyncSession,
) -> None:
    """Same-titled threads keep distinct ids and their own verified metadata."""
    user = await get_or_create_user_async(async_db)

    xmen_2013 = await _add_thread(
        async_db, user_id=user.id, title="Uncanny X-Men", queue_position=1
    )
    xmen_1963 = await _add_thread(
        async_db, user_id=user.id, title="Uncanny X-Men", queue_position=2
    )
    abe_mapped = await _add_thread(
        async_db, user_id=user.id, title="Abe Sapien", queue_position=3
    )
    abe_unmapped = await _add_thread(
        async_db, user_id=user.id, title="Abe Sapien", queue_position=4
    )
    pending_only = await _add_thread(
        async_db, user_id=user.id, title="Candidate Only", queue_position=5
    )

    await _add_series_identity(
        async_db,
        thread=xmen_2013,
        external_id="xmen-2013",
        metadata={
            "start_year": "2013",
            "name": "Uncanny X-Men",
            "publisher": {"name": "Marvel"},
        },
    )
    await _add_series_identity(
        async_db,
        thread=xmen_1963,
        external_id="xmen-1963",
        metadata={
            "start_year": "1963",
            "name": "Uncanny X-Men",
            "publisher": {"name": "Marvel"},
        },
    )
    await _add_series_identity(
        async_db,
        thread=abe_mapped,
        external_id="abe-2003",
        metadata={
            "start_year": "2003",
            "name": "Abe Sapien",
            "publisher": {"name": "Dark Horse"},
        },
    )
    await _add_series_identity(
        async_db,
        thread=pending_only,
        external_id="pending-only",
        metadata={"start_year": "1999", "publisher": {"name": "Image"}},
        status="candidate",
    )
    await async_db.commit()

    response = await list_queue_threads(
        async_db,
        user.id,
        search=None,
        sort="position",
        page_size=10,
        page_token=None,
    )

    rows = {row.id: row for row in response.threads}
    assert set(rows) == {
        xmen_2013.id,
        xmen_1963.id,
        abe_mapped.id,
        abe_unmapped.id,
        pending_only.id,
    }

    xmen_2013_row = rows[xmen_2013.id]
    xmen_1963_row = rows[xmen_1963.id]
    assert xmen_2013_row.title == xmen_1963_row.title == "Uncanny X-Men"
    assert xmen_2013_row.series_metadata is not None
    assert xmen_1963_row.series_metadata is not None
    assert xmen_2013_row.series_metadata.year == 2013
    assert xmen_1963_row.series_metadata.year == 1963
    # The provider name repeats the title, so neither row fabricates a volume.
    assert xmen_2013_row.series_metadata.volume is None
    assert xmen_1963_row.series_metadata.volume is None
    assert xmen_2013_row.series_metadata.publisher == "Marvel"
    assert xmen_1963_row.series_metadata.publisher == "Marvel"

    abe_row = rows[abe_mapped.id]
    assert abe_row.series_metadata is not None
    assert abe_row.series_metadata.year == 2003
    assert abe_row.series_metadata.publisher == "Dark Horse"

    # A distinct same-titled thread without a confirmed identity stays unmapped.
    assert rows[abe_unmapped.id].series_metadata is None

    # Candidate mappings are not confirmed identities and never surface.
    assert rows[pending_only.id].series_metadata is None
