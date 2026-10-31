"""Thread business logic and orchestration.

Services own business rules and transaction boundaries (commit/rollback/retry).
Query construction lives in ``app/repositories/thread_repository.py`` and
sibling repositories; HTTP status mapping lives in routers.
"""

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.reading_eligibility_service import (
    get_execution_eligibility,
    project_thread_responses,
)

from app.models import Event, Issue, Thread
from app.models.thread import EXCLUDED_STATUS, normalize_format_value, normalize_notes_value
from app.repositories import (
    continuity_repository,
    issue_repository,
    reading_session_repository,
    thread_repository,
)
from app.schemas import (
    ComicVineMappingHealth,
    ComicVineMappingStatus,
    PotentialDuplicateMatch,
    PotentialDuplicateMatchType,
    QueueSeriesMetadata,
    QueueThreadListItem,
    QueueThreadListResponse,
    ReactivateRequest,
    RollResponse,
    SetCurrentIssueResponse,
    ThreadCreate,
    ThreadDetail,
    ThreadResponse,
    ThreadUpdate,
)
from app.schemas.tags import TagResponse, TagTargetType
from app.services.queue_display import display_position, display_positions
from app.services.reading_effort import publication_year_from_metadata
from app.services.errors import ConflictError, ForbiddenError, InvalidRequestError, NotFoundError
from app.services.issue_tracking import apply_thread_issue_tracking_state
from app.services.ownership_guard import (
    require_frontier_in_thread,
    require_session_pending_consistent,
)
from app.services.snooze_service import derive_effective_roll_excluded_thread_ids
from app.services.tag_inheritance_service import TagInheritanceService
from app.services.tag_service import purge_target_assignments
from app.services.queue_pagination import (
    QueueCursor,
    QueueSort,
    build_cursor_values_from_row,
    decode_queue_cursor,
    encode_queue_cursor,
    normalize_queue_search,
)
from app.services.thread_issue_stats import load_issue_stats
from app.services.title_similarity import MIN_TITLE_SIMILARITY, title_similarity
from comic_pile.reading_session import get_current_die, get_or_create
from comic_pile.dependencies import format_blocking_reason, get_blocking_explanations

logger = logging.getLogger(__name__)

#: Maximum possible-existing-volume matches returned by one advisory check.
MAX_POTENTIAL_DUPLICATE_MATCHES = 5


async def _require_owned_thread(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
    *,
    for_update: bool = False,
) -> Thread:
    """Return a user-owned thread or raise a 404-mapped NotFoundError.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.
        for_update: Lock the row for update when True.

    Returns:
        The owned thread.

    Raises:
        NotFoundError: When the thread does not exist for this user.
    """
    thread = await thread_repository.find_owned(db, user_id, thread_id, for_update=for_update)
    if thread is None:
        raise NotFoundError(f"Thread {thread_id} not found")
    return thread


async def thread_to_response(
    thread: Thread,
    db: AsyncSession,
    issue_number_map: dict[int, str] | None = None,
    issues_remaining_map: dict[int, int] | None = None,
    position_map: dict[int, int] | None = None,
) -> ThreadResponse:
    """Convert Thread model to ThreadResponse.

    Args:
        thread: Thread model instance.
        db: Async database session for computing issues_remaining (fallback only).
        issue_number_map: Pre-fetched mapping of issue ID → issue_number.
            When provided, avoids per-thread DB lookups for next_unread_issue_number.
        issues_remaining_map: Pre-fetched mapping of thread ID → unread count.
            When provided and the thread uses issue tracking, avoids a per-thread
            COUNT query. Single-thread callers may omit this to use the per-row
            fallback.

        position_map: Optional precomputed whole-Queue display ordinals.

    Returns:
        ThreadResponse schema.
    """
    if issues_remaining_map is not None and thread.uses_issue_tracking():
        issues_remaining = issues_remaining_map.get(thread.id, 0)
    else:
        issues_remaining = await thread.get_issues_remaining(db)
    reading_progress = thread.reading_progress

    format_value = normalize_format_value(thread.format)

    next_unread_issue_id = thread.next_unread_issue_id
    next_unread_issue_number: str | None = None
    if next_unread_issue_id is not None:
        if issue_number_map is not None:
            next_unread_issue_number = issue_number_map.get(next_unread_issue_id)
        else:
            next_issue = await issue_repository.get_issue(db, next_unread_issue_id)
            if next_issue:
                next_unread_issue_number = next_issue.issue_number

    position = (
        position_map.get(thread.id, 0)
        if position_map is not None
        else await display_position(db, thread)
    )
    return ThreadResponse(
        id=thread.id,
        title=thread.title,
        format=format_value,
        issues_remaining=issues_remaining,
        queue_position=position,
        status=thread.status,
        last_rating=thread.last_rating,
        last_activity_at=thread.last_activity_at,
        notes=thread.notes,
        is_test=thread.is_test,
        is_blocked=thread.is_blocked,
        blocking_reasons=[],
        created_at=thread.created_at,
        total_issues=thread.total_issues,
        reading_progress=reading_progress,
        next_unread_issue_id=next_unread_issue_id,
        next_unread_issue_number=next_unread_issue_number,
        manual_creator_credits=thread.manual_creator_credits,
    )


async def threads_to_responses(
    threads: list[Thread], db: AsyncSession, position_map: dict[int, int] | None = None
) -> list[ThreadResponse]:
    """Convert Thread models to responses with batched lookups.

    Args:
        threads: Threads appearing in one response payload.
        db: Database session.
        position_map: Optional whole-Queue display positions from the page query.

    Returns:
        One ThreadResponse per input thread, in input order.
    """
    remaining_map, issue_map = await load_issue_stats(threads, db)
    positions = position_map
    if not positions:
        positions = {}
        for user_id in {thread.user_id for thread in threads}:
            positions.update(await display_positions(db, user_id))
    return [
        await thread_to_response(
            thread,
            db,
            issue_number_map=issue_map,
            issues_remaining_map=remaining_map,
            position_map=positions,
        )
        for thread in threads
    ]


def _clean_metadata_text(value: object) -> str | None:
    """Return collapsed display text from a stored provider metadata value.

    Args:
        value: Raw metadata value from ``ExternalIdentity.metadata_json``.

    Returns:
        Whitespace-collapsed non-empty text, or ``None`` when the value cannot
        be shown as a label.
    """
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _coerce_publication_year(value: object) -> int | None:
    """Return a plausible publication year from a stored provider value.

    ComicVine returns ``start_year`` as a numeric string (``"1999"``), while
    imported catalog metadata may store it as an integer. Booleans are rejected
    even though ``bool`` is an ``int`` subclass.

    Args:
        value: Stored ``start_year`` metadata value.

    Returns:
        The four-digit year, or ``None`` when the value is not a plausible year.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        year = value
    elif isinstance(value, str) and value.strip().isdigit() and len(value.strip()) == 4:
        year = int(value.strip())
    else:
        return None
    return year if 1000 <= year <= 9999 else None


def _extract_run_label(
    metadata: dict[str, object],
    *,
    normalized_title: str,
) -> str | None:
    """Return the stored provider run/volume name when it adds identification.

    ComicVine stores no numeric volume label, so the only truthful run label is
    the provider's own volume name. It is used only when it differs from the
    thread title, because repeating the title would not identify a run.

    Args:
        metadata: One confirmed series ``metadata_json`` document.
        normalized_title: Whitespace-collapsed, case-folded thread title.

    Returns:
        The stored run label, or ``None`` when no distinguishing name exists.
    """
    volume_ref = metadata.get("volume")
    candidates: list[object] = []
    if isinstance(volume_ref, dict):
        candidates.append(volume_ref.get("name"))
    candidates.append(metadata.get("volume_name"))
    candidates.append(metadata.get("name"))
    for candidate in candidates:
        label = _clean_metadata_text(candidate)
        if label is not None and label.casefold() != normalized_title:
            return label
    return None


def _extract_publisher(metadata: dict[str, object]) -> str | None:
    """Return the confirmed publisher name from one series metadata document.

    Args:
        metadata: One confirmed series ``metadata_json`` document.

    Returns:
        The publisher name, or ``None`` when the stored value has no usable name.
    """
    publisher = metadata.get("publisher")
    if isinstance(publisher, dict):
        return _clean_metadata_text(publisher.get("name"))
    return _clean_metadata_text(publisher)


def _extract_series_metadata(
    series_metadata_docs: list[dict[str, object]],
    *,
    thread_title: str,
) -> tuple[int | None, str | None, str | None]:
    """Extract confirmed series year, volume, and publisher from one identity.

    Reads only stored, confirmed provider metadata. Never fabricates values from
    a display title or ComicVine numeric ID. Only the canonical identity document
    (the repository's first result, ordered by confirmed-mapping confidence) is
    interpreted, so fields from two different series identities are never
    combined into one Queue row.

    Args:
        series_metadata_docs: Confirmed series ``metadata_json`` documents for one
            thread, in canonical confirmed-identity order.
        thread_title: The owning thread's display title, used only to avoid
            repeating the title as a run label.

    Returns:
        ``(series_year, series_volume, series_publisher)``, each ``None`` when no
        confirmed value is available.
    """
    if not series_metadata_docs:
        return None, None, None
    metadata = series_metadata_docs[0]
    if not isinstance(metadata, dict):
        return None, None, None

    normalized_title = " ".join(thread_title.split()).casefold()
    series_year = _coerce_publication_year(metadata.get("start_year"))
    if series_year is None:
        # Series identities exported from an issue-shaped document may carry a
        # publication date instead of a start year.
        series_year = publication_year_from_metadata(metadata)
    return (
        series_year,
        _extract_run_label(metadata, normalized_title=normalized_title),
        _extract_publisher(metadata),
    )


def build_comicvine_mapping_health(
    mapping_health: dict | None,
    total_issues: int | None = None,
) -> ComicVineMappingHealth | None:
    """Derive the ComicVine mapping health projection from a raw health row.

    Shared by the Queue list projection and the per-thread health endpoint so
    the two surfaces cannot drift on status derivation.
    """
    if mapping_health is None:
        return None

    tracked = mapping_health["tracked_issue_count"]
    confirmed = mapping_health["confirmed_issue_count"]
    needs_mapping = mapping_health["needs_mapping_count"]
    needs_review = mapping_health["needs_review_count"]
    metadata_missing = mapping_health.get("metadata_missing_count", 0)
    has_issues = mapping_health["has_issues"]

    if not has_issues and total_issues is None:
        # Legacy thread without issue tracking - mapping not applicable
        status = ComicVineMappingStatus.not_applicable
    elif tracked == 0:
        # Thread uses issue tracking but has no issues yet
        status = ComicVineMappingStatus.not_applicable
    elif needs_review > 0:
        status = ComicVineMappingStatus.needs_review
    elif confirmed == tracked and tracked > 0 and metadata_missing == 0:
        status = ComicVineMappingStatus.fully_mapped
    elif confirmed > 0:
        status = ComicVineMappingStatus.partial
    else:
        status = ComicVineMappingStatus.unresolved

    return ComicVineMappingHealth(
        status=status,
        tracked_issue_count=tracked,
        confirmed_issue_count=confirmed,
        needs_mapping_count=needs_mapping,
        needs_review_count=needs_review,
        metadata_missing_count=metadata_missing,
    )


def to_queue_list_item(
    tr: ThreadResponse,
    mapping_health: dict | None = None,
    tags: list[TagResponse] | None = None,
    series_metadata_docs: list[dict[str, object]] | None = None,
) -> QueueThreadListItem:
    """Convert a full ThreadResponse to a narrow QueueThreadListItem.

    Deliberately drops detail-only fields (last_rating, is_test,
    reading_progress, next_unread_issue_id) to reduce payload size for list
    views.

    Args:
        tr: Full thread response.
        mapping_health: Optional pre-computed mapping health row from the
            batched repository query. When provided, used to construct the
            ComicVineMappingHealth projection.
        tags: Optional pre-fetched visible direct tags for the thread, read in
            one batched query for the whole page.
        series_metadata_docs: Optional confirmed series identity metadata
            documents for this thread, read in one batched query for the whole
            page. When provided, used to project the verified year, volume, and
            publisher. An empty or missing list marks the row as an unmapped
            series instead of guessing an identity.

    Returns:
        Narrow list-item projection of the thread response.
    """
    format_value = normalize_format_value(tr.format)

    comicvine_mapping = build_comicvine_mapping_health(mapping_health, tr.total_issues)

    series_metadata = None
    if series_metadata_docs:
        series_year, series_volume, series_publisher = _extract_series_metadata(
            series_metadata_docs, thread_title=tr.title
        )
        series_metadata = QueueSeriesMetadata(
            year=series_year,
            volume=series_volume,
            publisher=series_publisher,
        )

    return QueueThreadListItem(
        id=tr.id,
        title=tr.title,
        format=format_value,
        issues_remaining=tr.issues_remaining,
        queue_position=tr.queue_position,
        status=tr.status,
        last_activity_at=tr.last_activity_at,
        is_blocked=tr.is_blocked,
        blocking_reasons=tr.blocking_reasons,
        total_issues=tr.total_issues,
        next_unread_issue_number=tr.next_unread_issue_number,
        notes=tr.notes,
        created_at=tr.created_at,
        comicvine_mapping=comicvine_mapping,
        manual_creator_credits=tr.manual_creator_credits,
        tags=tags or [],
        series_metadata=series_metadata,
    )


async def list_stale_thread_responses(
    db: AsyncSession,
    user_id: int,
    days: int,
    snoozed_ids: list[int] | None = None,
    page_size: int | None = None,
) -> list[ThreadResponse]:
    """Build responses for threads not read in the given number of days.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        days: Number of days to consider threads stale.
        snoozed_ids: Thread IDs currently snoozed in the session; these are
            excluded from the stale result.
        page_size: Optional maximum number of responses to return.

    Returns:
        Responses for stale threads ordered by oldest activity first.
    """
    from app.services.snooze_service import derive_cross_session_excluded_thread_ids

    reading_session = await reading_session_repository.fetch_active_reading_session(db, user_id)
    current_snoozed = reading_session.snoozed_thread_ids if reading_session is not None else []
    derived = await derive_cross_session_excluded_thread_ids(db, user_id)
    snoozed_ids = sorted(set(snoozed_ids or []) | set(current_snoozed or []) | derived)
    cutoff_date = datetime.now(UTC) - timedelta(days=days)
    eligibility = await get_execution_eligibility(db, user_id)
    if eligibility is not None and reading_session is not None:
        snoozed_ids = sorted(set(snoozed_ids) | set(reading_session.skipped_thread_ids or []))
    eligibility_args = {"eligibility": eligibility} if eligibility is not None else {}
    threads = await thread_repository.fetch_stale_threads(
        db, user_id, cutoff_date, snoozed_ids=snoozed_ids, page_size=page_size, **eligibility_args
    )
    return project_thread_responses(await threads_to_responses(threads, db), eligibility)


async def list_queue_threads(
    db: AsyncSession,
    user_id: int,
    *,
    search: str | None,
    sort: str,
    page_size: int,
    page_token: str | None,
) -> QueueThreadListResponse:
    """List ACTIVE threads with deterministic cursor-based pagination.

    Every retained sort has a deterministic cursor contract with stable
    tie-breakers so that search results remain correct across multiple pages.
    Changing ``search`` or ``sort`` invalidates any prior cursor.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        search: Optional case-insensitive title search filter.
        sort: Validated sort order – ``position``, ``title``, or ``created``.
        page_size: Number of threads to return per page (max 200).
        page_token: Opaque cursor token for pagination continuation.

    Returns:
        QueueThreadListResponse with paginated ACTIVE threads and next_page_token if
        more exist, plus the authoritative whole-queue ``active_count``.

    Raises:
        InvalidRequestError: When the page token is stale or malformed.
    """
    eligibility = await get_execution_eligibility(db, user_id)
    eligibility_args = {"eligibility": eligibility} if eligibility is not None else {}
    validated_sort: QueueSort = cast(QueueSort, sort)
    normalized_search = normalize_queue_search(search)

    # Authoritative whole-queue total. Computed separately so it never depends
    # on the loaded page, the search filter, or the sort order (issue #2568).
    active_count = await thread_repository.count_active_threads(db, user_id)

    cursor = None
    if page_token:
        try:
            cursor = decode_queue_cursor(
                page_token,
                sort=validated_sort,
                search=search,
                execution="option_e" if eligibility is not None else "legacy",
            )
        except ValueError as exc:
            raise InvalidRequestError(str(exc)) from exc

    position_map: dict[int, int] = {}
    series_metadata_map: dict[int, list[dict[str, object]]] = {}
    threads = await thread_repository.fetch_queue_page(
        db,
        user_id,
        search=normalized_search,
        sort=validated_sort,
        cursor=cursor,
        limit=page_size + 1,
        position_map=position_map,
        series_metadata_map=series_metadata_map,
        **eligibility_args,
    )

    has_more = len(threads) > page_size
    threads_to_return = threads[:page_size]

    thread_responses = await threads_to_responses(threads_to_return, db, position_map)

    # Fetch ComicVine mapping health for issue-tracking threads on this page only
    # (batched, no N+1). Legacy threads without total_issues skip the query
    # entirely, so their per-page SQL work stays the page read, the active_count
    # read, and the bounded tag and confirmed-series reads (#3425, #3605).
    tracked_ids = {tr.id for tr in thread_responses if tr.total_issues is not None}
    mapping_health_map = await thread_repository.fetch_comicvine_mapping_health(db, tracked_ids)

    thread_responses = project_thread_responses(thread_responses, eligibility)

    # One bounded tag read for the whole page (issue #3425) so Queue rows show
    # tags without a per-row query.
    tags_map = await TagInheritanceService(db).get_threads_direct_tags(
        user_id, [tr.id for tr in thread_responses]
    )

    queue_items = [
        to_queue_list_item(
            tr,
            mapping_health_map.get(tr.id),
            tags_map.get(tr.id, []),
            series_metadata_map.get(tr.id),
        )
        for tr in thread_responses
    ]

    next_token = None
    if has_more and threads_to_return:
        last = threads_to_return[-1]
        page_cursor = QueueCursor(
            sort=validated_sort,
            execution="option_e" if eligibility is not None else "legacy",
            search=normalized_search,
            values=build_cursor_values_from_row(validated_sort, last, eligibility),
        )
        next_token = encode_queue_cursor(page_cursor)

    return QueueThreadListResponse(
        threads=queue_items,
        next_page_token=next_token,
        active_count=active_count,
    )


async def list_completed_threads(
    db: AsyncSession,
    user_id: int,
    *,
    search: str | None,
    sort: str,
    page_size: int,
    page_token: str | None,
) -> QueueThreadListResponse:
    """List COMPLETED threads with deterministic cursor-based pagination.

    Every retained sort has a deterministic cursor contract with stable
    tie-breakers so that search results remain correct across multiple pages.
    Changing ``search`` or ``sort`` invalidates any prior cursor.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        search: Optional case-insensitive title search filter.
        sort: Validated sort order – ``position``, ``title``, or ``created``.
        page_size: Number of threads to return per page (max 200).
        page_token: Opaque cursor token for pagination continuation.

    Returns:
        QueueThreadListResponse with paginated COMPLETED threads and next_page_token if
        more exist.

    Raises:
        InvalidRequestError: When the page token is stale or malformed.
    """
    validated_sort: QueueSort = cast(QueueSort, sort)
    # Completed threads hold no live queue positions, so ``position`` is an
    # alias for ``created`` throughout this collection. Normalizing up front
    # keeps the cursor contract, the ORDER BY columns, and the keyset filter
    # on one consistent sort instead of minting ``position`` tokens that carry
    # ``created`` values.
    effective_sort: QueueSort = "created" if validated_sort == "position" else validated_sort
    normalized_search = normalize_queue_search(search)

    cursor = None
    if page_token:
        try:
            cursor = decode_queue_cursor(page_token, sort=effective_sort, search=search)
        except ValueError as exc:
            raise InvalidRequestError(str(exc)) from exc

    series_metadata_map: dict[int, list[dict[str, object]]] = {}
    threads = await thread_repository.fetch_completed_page(
        db,
        user_id,
        search=normalized_search,
        sort=effective_sort,
        cursor=cursor,
        limit=page_size + 1,
        series_metadata_map=series_metadata_map,
    )

    has_more = len(threads) > page_size
    threads_to_return = threads[:page_size]

    thread_responses = await threads_to_responses(threads_to_return, db)

    # Fetch ComicVine mapping health for issue-tracking threads on this page only
    # (batched, no N+1). Legacy threads without total_issues skip the query
    # entirely, so their per-page SQL work stays the page read plus the bounded
    # tag and confirmed-series reads (#3425, #3605).
    tracked_ids = {tr.id for tr in thread_responses if tr.total_issues is not None}
    mapping_health_map = await thread_repository.fetch_comicvine_mapping_health(db, tracked_ids)

    # One bounded tag read for the whole page (issue #3425) so Queue rows show
    # tags without a per-row query.
    tags_map = await TagInheritanceService(db).get_threads_direct_tags(
        user_id, [tr.id for tr in thread_responses]
    )

    queue_items = [
        to_queue_list_item(
            tr,
            mapping_health_map.get(tr.id),
            tags_map.get(tr.id, []),
            series_metadata_map.get(tr.id),
        )
        for tr in thread_responses
    ]

    next_token = None
    if has_more and threads_to_return:
        last = threads_to_return[-1]
        page_cursor = QueueCursor(
            sort=effective_sort,
            search=normalized_search,
            values=build_cursor_values_from_row(effective_sort, last),
        )
        next_token = encode_queue_cursor(page_cursor)

    return QueueThreadListResponse(
        threads=queue_items,
        next_page_token=next_token,
    )


async def list_excluded_threads(
    db: AsyncSession,
    user_id: int,
    *,
    search: str | None,
    sort: str,
    page_size: int,
    page_token: str | None,
) -> QueueThreadListResponse:
    """List EXCLUDED threads with deterministic cursor-based pagination.

    These are the series a reader removed from the active queue without
    deleting them (#3807). The rows, their issues, ratings, mappings, and
    reading-plan memberships are all intact, so this is the discoverable
    library view they are restored from.

    Args:
        db: Database session.
        user_id: Owner of the threads.
        search: Optional case-insensitive title search filter.
        sort: Validated sort order – ``position``, ``title``, or ``created``.
            ``position`` has no meaning off the active queue and is read as
            ``created``.
        page_size: Number of threads to return per page (max 200).
        page_token: Opaque cursor token for pagination continuation.

    Returns:
        QueueThreadListResponse with paginated EXCLUDED threads.

    Raises:
        InvalidRequestError: When the page token is stale or malformed.
    """
    validated_sort: QueueSort = cast(QueueSort, sort)
    # Excluded threads do not have queue positions; normalize position to created.
    effective_sort: QueueSort = "created" if validated_sort == "position" else validated_sort
    normalized_search = normalize_queue_search(search)

    cursor = None
    if page_token:
        try:
            cursor = decode_queue_cursor(page_token, sort=effective_sort, search=search)
        except ValueError as exc:
            raise InvalidRequestError(str(exc)) from exc

    series_metadata_map: dict[int, list[dict[str, object]]] = {}
    threads = await thread_repository.fetch_excluded_page(
        db,
        user_id,
        search=normalized_search,
        sort=effective_sort,
        cursor=cursor,
        limit=page_size + 1,
        series_metadata_map=series_metadata_map,
    )

    has_more = len(threads) > page_size
    threads_to_return = threads[:page_size]

    thread_responses = await threads_to_responses(threads_to_return, db)

    tracked_ids = {tr.id for tr in thread_responses if tr.total_issues is not None}
    mapping_health_map = await thread_repository.fetch_comicvine_mapping_health(db, tracked_ids)
    tags_map = await TagInheritanceService(db).get_threads_direct_tags(
        user_id, [tr.id for tr in thread_responses]
    )

    queue_items = [
        to_queue_list_item(
            tr,
            mapping_health_map.get(tr.id),
            tags_map.get(tr.id, []),
            series_metadata_map.get(tr.id),
        )
        for tr in thread_responses
    ]

    next_token = None
    if has_more and threads_to_return:
        last = threads_to_return[-1]
        page_cursor = QueueCursor(
            sort=effective_sort,
            search=normalized_search,
            values=build_cursor_values_from_row(effective_sort, last),
        )
        next_token = encode_queue_cursor(page_cursor)

    return QueueThreadListResponse(
        threads=queue_items,
        next_page_token=next_token,
    )


async def completed_threads_html(db: AsyncSession, user_id: int) -> str:
    """Render completed threads as option elements for the reactivation modal.

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        HTML string with option elements for completed threads.
    """
    threads = await thread_repository.fetch_completed_threads(db, user_id)
    options = "\n".join(
        f'<option value="{thread.id}">{thread.title} ({thread.normalize_format()})</option>'
        for thread in threads
    )
    return f'<option value="">Select a completed thread...</option>\n{options}'


async def active_threads_html(db: AsyncSession, user_id: int) -> str:
    """Render active threads as radio buttons for the override modal.

    Args:
        db: Database session.
        user_id: Owner of the threads.

    Returns:
        HTML string with radio button elements for active threads.
    """
    threads = await thread_repository.fetch_active_threads(db, user_id)
    items = "\n".join(
        f'<div class="flex items-center p-2 hover:bg-gray-50 rounded">'
        f'<input type="radio" name="thread_id" value="{thread.id}" id="thread-{thread.id}" class="mr-3">'
        f'<label for="thread-{thread.id}" class="flex-1 cursor-pointer">'
        f'<span class="font-medium">{thread.title}</span>'
        f'<span class="text-sm text-gray-500 ml-2">({thread.normalize_format()})</span>'
        f"</label></div>"
        for thread in threads
    )
    return items or '<p class="text-gray-500 text-center py-4">No active threads available</p>'


async def find_potential_duplicate_matches(
    db: AsyncSession,
    user_id: int,
    *,
    title: str,
    format_value: str,
    comicvine_volume_id: int | None = None,
    exclude_thread_id: int | None = None,
) -> list[PotentialDuplicateMatch]:
    """Find the reader's existing series that may already be this volume.

    Canonical ComicVine volume identity is the only strong match. Title
    resemblance produces an explicitly uncertain suggestion, because real comic
    volumes legitimately share titles across relaunches, editions, and formats.
    Publication year, format, and the existing thread's own volume accompany
    every match as disambiguating context.

    This function is read-only: viewing a warning never merges, deletes, or
    rewrites reader data.

    Args:
        db: Database session.
        user_id: Owner whose library is searched.
        title: Proposed series title.
        format_value: Proposed series format (normalized before use).
        comicvine_volume_id: Canonical ComicVine volume ID when the candidate
            has one.
        exclude_thread_id: Thread to leave out, so a rename never warns about
            the series being renamed.

    Returns:
        Possible existing volumes, strong matches first, then title matches by
        descending resemblance.
    """
    strong_threads: list[Thread] = []
    if comicvine_volume_id is not None:
        strong_threads = await thread_repository.find_owned_threads_linked_to_comicvine_volume(
            db,
            user_id,
            comicvine_volume_id,
            exclude_thread_id=exclude_thread_id,
        )

    normalized_format = normalize_format_value(format_value)
    strong_ids = {thread.id for thread in strong_threads}
    considered: list[tuple[float, bool, Thread]] = []
    for thread in await thread_repository.find_owned_threads_with_similar_titles(
        db,
        user_id,
        title,
        exclude_thread_id=exclude_thread_id,
    ):
        if thread.id in strong_ids:
            continue
        similarity = title_similarity(title, thread.title)
        if similarity >= MIN_TITLE_SIMILARITY:
            considered.append(
                (similarity, normalize_format_value(thread.format) == normalized_format, thread)
            )

    # Strong identity matches are always shown. Title resemblance fills the
    # remaining slots, best first. The proposed format is disambiguating context
    # only: a same-format edition ranks above a cross-format one at equal
    # resemblance, and thread ID keeps the order deterministic.
    considered.sort(key=lambda entry: (-entry[0], not entry[1], entry[2].id))
    remaining_slots = max(MAX_POTENTIAL_DUPLICATE_MATCHES - len(strong_threads), 0)
    candidates: list[tuple[Thread, PotentialDuplicateMatchType]] = [
        (thread, PotentialDuplicateMatchType.SAME_COMICVINE_VOLUME) for thread in strong_threads
    ] + [
        (thread, PotentialDuplicateMatchType.SIMILAR_TITLE)
        for _similarity, _same_format, thread in considered[:remaining_slots]
    ]

    series_context = await thread_repository.fetch_confirmed_comicvine_series_by_thread(
        db,
        user_id,
        [thread.id for thread, _match_type in candidates],
    )
    unread_counts, _next_unread_numbers = await load_issue_stats(
        [thread for thread, _match_type in candidates], db
    )

    matches: list[PotentialDuplicateMatch] = []
    for thread, match_type in candidates:
        existing_volume_id, metadata = series_context.get(thread.id, (None, {}))
        start_year = _coerce_publication_year(metadata.get("start_year"))
        if start_year is None:
            # Series identities exported from an issue-shaped document may carry
            # a publication date instead of a provider start year.
            start_year = publication_year_from_metadata(metadata)
        matches.append(
            PotentialDuplicateMatch(
                thread_id=thread.id,
                title=thread.title,
                format=normalize_format_value(thread.format),
                status=thread.status,
                issues_remaining=(
                    unread_counts.get(thread.id, 0)
                    if thread.uses_issue_tracking()
                    else thread.issues_remaining
                ),
                total_issues=thread.total_issues,
                comicvine_volume_id=existing_volume_id,
                start_year=start_year,
                match_type=match_type,
            )
        )
    return matches


async def create_thread_with_retry(
    db: AsyncSession, user_id: int, thread_data: ThreadCreate
) -> ThreadResponse:
    """Create a new thread at the end of the user's queue with deadlock retry.

    Duplicate create submissions with an identical fingerprint (owner, title,
    format, remaining issue count) inside a short window merge into the thread
    created by the first submit instead of inserting a second copy (#3466).

    Args:
        db: Database session.
        user_id: Owner of the new thread.
        thread_data: Thread creation data.

    Returns:
        ThreadResponse with the created thread, or with the recently created
        duplicate that a repeat submission merged into.

    Raises:
        RuntimeError: If creation keeps deadlocking past the retry budget.
    """
    max_retries = 3
    initial_delay = 0.1
    retries = 0

    # Idempotency window for duplicate submissions (double-click protection)
    duplicate_window = timedelta(seconds=5)

    while retries < max_retries:
        try:
            # Merge duplicate submissions (#3466): a double-clicked "Create
            # Series" sends the same payload twice; return the thread created
            # by the first submit instead of inserting an identical duplicate.
            existing = await thread_repository.find_recent_duplicate(
                db,
                user_id=user_id,
                title=thread_data.title,
                format_value=normalize_format_value(thread_data.format),
                issues_remaining=thread_data.issues_remaining,
                since=datetime.now(UTC) - duplicate_window,
            )
            if existing is not None:
                return await thread_to_response(existing, db)

            max_position = await thread_repository.max_queue_position(db, user_id)
            format_value = normalize_format_value(thread_data.format)

            new_thread = Thread(
                title=thread_data.title,
                format=format_value,
                issues_remaining=thread_data.issues_remaining,
                total_issues=thread_data.total_issues,
                queue_position=max_position + 1,
                user_id=user_id,
                notes=normalize_notes_value(thread_data.notes),
                manual_creator_credits=thread_data.manual_creator_credits,
                is_test=thread_data.is_test,
            )
            await thread_repository.insert_thread(db, new_thread)
            await db.commit()
            await db.refresh(new_thread)

            return await thread_to_response(new_thread, db)
        except OperationalError as e:
            if "deadlock" in str(e).lower():
                await db.rollback()
                retries += 1
                if retries >= max_retries:
                    raise
                delay = initial_delay * (2 ** (retries - 1))
                await asyncio.sleep(delay)
            else:
                raise

    raise RuntimeError(f"Failed to create thread after {max_retries} retries")


async def get_thread_detail(db: AsyncSession, user_id: int, thread_id: int) -> ThreadDetail:
    """Build the detail payload for one owned thread.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.

    Returns:
        ThreadDetail for the thread.

    Raises:
        NotFoundError: When the thread does not exist for this user.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)
    tr = await thread_to_response(thread, db)
    eligibility = await get_execution_eligibility(db, user_id)
    projected = project_thread_responses([tr], eligibility)[0]
    return ThreadDetail(**projected.model_dump())


async def update_thread(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
    thread_data: ThreadUpdate,
) -> ThreadResponse:
    """Apply a partial update to an owned thread.

    Only legacy (non-issue-tracked) threads honor manual ``issues_remaining``
    edits; such edits also drive the active/completed status transition.

    ``notes`` follows explicit-presence semantics (issue #3629): when the client
    includes the field, its value is written verbatim, so an emptied field
    (``""``) or an explicit ``null`` clears the stored notes instead of silently
    preserving them. Omitting the field (for example a title-only edit) leaves
    notes untouched. A blank or whitespace-only value is stored as ``NULL`` so a
    cleared series reads back as "no notes" everywhere.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.
        thread_data: Partial update data.

    Returns:
        ThreadResponse with updated thread details.

    Raises:
        NotFoundError: When the thread does not exist for this user.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)
    if thread_data.title is not None:
        thread.title = thread_data.title
    if thread_data.format is not None:
        thread.format = normalize_format_value(thread_data.format)
    if thread_data.issues_remaining is not None:
        if not thread.uses_issue_tracking():
            # This edit can change queue membership, and computing the append
            # position issues a query that would autoflush the dirty thread
            # row. Take the queue lock first so row locks always follow it
            # (same ordering as move/shuffle) and cannot deadlock.
            await thread_repository.acquire_queue_lock(db, user_id)
            thread.issues_remaining = thread_data.issues_remaining
            if thread.issues_remaining == 0:
                if thread.apply_derived_status("completed"):
                    thread.queue_position = 0
                    await thread_repository.renormalize_queue_positions(db, user_id)
            else:
                if thread.apply_derived_status("active") and thread.queue_position < 1:
                    thread.queue_position = (
                        await thread_repository.max_queue_position(db, user_id) + 1
                    )
                    await thread_repository.renormalize_queue_positions(db, user_id)
    if "notes" in thread_data.model_fields_set:
        thread.notes = normalize_notes_value(thread_data.notes)
    if thread_data.manual_creator_credits is not None:
        thread.manual_creator_credits = thread_data.manual_creator_credits
    if thread_data.is_test is not None:
        thread.is_test = thread_data.is_test
    await db.commit()
    await db.refresh(thread)

    # Pre-fetch statistics with the same combined single-query loader as
    # threads_to_responses, to avoid per-thread DB round-trips on the update
    # path (issue #3442) and the second sequential stats query (issue #3463).
    if thread.uses_issue_tracking():
        issues_remaining_map, issue_number_map = await load_issue_stats([thread], db)
    else:
        issues_remaining_map = None
        issue_number_map = None

    return await thread_to_response(
        thread,
        db,
        issue_number_map=issue_number_map,
        issues_remaining_map=issues_remaining_map,
    )


async def delete_thread(db: AsyncSession, user_id: int, thread_id: int) -> None:
    """Delete an owned thread and detach dependent session state.

    Sessions pointing at the thread lose their pending pointer, continuity
    plans and rules that reference the thread or its issues are pruned so no
    orphaned steps remain, blocked flags are refreshed, and a tombstone event
    records the deletion.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.

    Raises:
        NotFoundError: When the thread does not exist for this user.
        InvalidRequestError: When the database refuses the deletion.
    """
    # Take the queue lock first to prevent deadlocks with concurrent shuffles.
    await thread_repository.renormalize_queue_positions(db, user_id)
    thread = await _require_owned_thread(db, user_id, thread_id)

    await reading_session_repository.detach_pending_thread_references_from_reading_sessions(
        db, thread_id
    )

    # Collect issue ids that will disappear with the thread for plan cleanup.
    deleted_issue_ids = await issue_repository.issue_ids_for_thread(db, thread_id)

    # Tag assignments point at polymorphic target ids with no foreign key, so
    # drop the thread's own assignments and its issues' assignments here.
    await purge_target_assignments(db, TagTargetType.THREAD.value, [thread_id])
    await purge_target_assignments(db, TagTargetType.ISSUE.value, deleted_issue_ids)

    delete_event = Event(
        type="delete",
        timestamp=datetime.now(UTC),
        thread_id=None,
    )
    db.add(delete_event)
    try:
        # Prune continuity plans that reference this thread or its issues.
        # This prevents orphaned steps that would otherwise 404 on reopen.
        plans = await continuity_repository.plans_for_user(db, user_id)
        for plan in plans:
            original = list(plan.nodes_json or [])
            pruned: list[dict[str, object]] = []
            changed = False
            for node in original:
                try:
                    ntype = str(node.get("node_type", ""))
                    ref = int(node.get("ref_id", 0))
                except (TypeError, ValueError):
                    pruned.append(node)
                    continue
                if ntype == "thread" and ref == thread_id:
                    changed = True
                    continue
                if ntype == "issue" and ref in deleted_issue_ids:
                    changed = True
                    continue
                pruned.append(node)
            if changed:
                # Renormalize contiguous positions per lane after removal.
                by_lane: dict[str, list[dict[str, object]]] = {}
                for n in pruned:
                    by_lane.setdefault(str(n.get("lane_id", "")), []).append(n)
                normalized: list[dict[str, object]] = []
                for _lane_id, lane_nodes in by_lane.items():
                    lane_nodes.sort(key=lambda x: int(x.get("position", 0)))
                    for idx, n in enumerate(lane_nodes):
                        n["position"] = idx
                        normalized.append(n)
                plan.nodes_json = normalized
                # Keep the normalized membership/provenance in step with the
                # pruned JSON so deleted issues leave no orphan plan rows.
                from app.schemas.continuity_plan import ContinuityPlanNode
                from app.services.reading_plan_normalization import (
                    rebuild_plan_membership,
                )

                await rebuild_plan_membership(
                    db,
                    plan_id=plan.id,
                    nodes=[ContinuityPlanNode.model_validate(n) for n in normalized],
                )
                # Remove plan-owned rules that pointed at deleted issues.
                marker = f"continuity-plan:{plan.id}"
                if deleted_issue_ids:
                    await continuity_repository.delete_plan_rules_referencing_issues(
                        db, user_id, marker, deleted_issue_ids
                    )
                # If strict plan now has <2 nodes, remove remaining linear edges
                if len(pruned) < 2:
                    await continuity_repository.delete_rules_for_marker(db, user_id, marker)

        # Delete any continuity rules (non-plan-owned) that directly reference deleted issues.
        if deleted_issue_ids:
            await continuity_repository.delete_rules_referencing_issues(
                db, user_id, deleted_issue_ids
            )

        from comic_pile.dependencies import refresh_user_blocked_status

        # Canonical Roll runtime (#2553): blocked state comes only from Thread
        # frontiers plus canonical Dependency rows. The continuity-graph
        # fallback no longer exists.
        await refresh_user_blocked_status(user_id, db)

        await thread_repository.delete_thread(db, thread)
        await thread_repository.renormalize_queue_positions(db, user_id)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise InvalidRequestError(f"Cannot delete thread: {exc}") from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("Unexpected error deleting thread %s", thread_id)
        raise InvalidRequestError(f"Cannot delete thread: {exc}") from exc


async def exclude_thread(db: AsyncSession, user_id: int, thread_id: int) -> ThreadResponse:
    """Remove a thread from the active queue without deleting its data.

    The thread's status is changed to :data:`~app.models.thread.EXCLUDED_STATUS`
    and its queue position is cleared. Reading history, issues, ratings,
    mappings, and reading-plan memberships are preserved untouched, and the
    derived-status paths (reading, rating, CBL sync, reconciliation) keep the
    series excluded until it is explicitly restored.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.

    Returns:
        ThreadResponse for the excluded thread.

    Raises:
        NotFoundError: When the thread does not exist for this user.
        InvalidRequestError: When the thread is not active.
    """
    # Take the queue lock first to prevent deadlocks with concurrent shuffles.
    await thread_repository.renormalize_queue_positions(db, user_id)
    thread = await _require_owned_thread(db, user_id, thread_id, for_update=True)
    if thread.is_excluded():
        # Idempotent: removing an already-excluded series is a no-op, not an error.
        return await thread_to_response(thread, db)
    if thread.status != "active":
        raise InvalidRequestError(f"Thread {thread_id} is not active and cannot be excluded")

    thread.status = EXCLUDED_STATUS
    thread.queue_position = 0
    # Leaving the queue ends any manual placement claim; restoring the series
    # must not silently revive a stale "keep me here" instruction (#3638).
    thread.queue_position_is_manual = False
    # This thread has now left the active set, so renumber the survivors as a
    # dense 1..N sequence before committing. The queue lock acquired at the
    # start of this function is still held by this transaction, so the rewrite
    # cannot interleave with a concurrent move or shuffle (#3924 review).
    await thread_repository.renormalize_queue_positions(db, user_id)
    await db.commit()
    await db.refresh(thread)
    return await thread_to_response(thread, db)


async def restore_thread(db: AsyncSession, user_id: int, thread_id: int) -> ThreadResponse:
    """Restore an excluded thread back to the queue without recreating it.

    The same Thread and Issue rows, issue numbers/positions, read state and
    timestamps, ratings and events, ComicVine mappings, and reading-plan
    memberships are reused verbatim; only the lifecycle status and queue
    position change. A series with no unread issue left is restored to the
    finished shelf instead of the active queue, because an ``active`` thread
    with an empty reading frontier would violate the completion invariant that
    Roll and the queue eligibility predicates rely on.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.

    Returns:
        ThreadResponse for the restored thread.

    Raises:
        NotFoundError: When the thread does not exist for this user.
        InvalidRequestError: When the thread is not excluded.
    """
    # Take the queue lock first to prevent deadlocks with concurrent shuffles.
    await thread_repository.renormalize_queue_positions(db, user_id)
    thread = await _require_owned_thread(db, user_id, thread_id, for_update=True)
    if not thread.is_excluded():
        raise InvalidRequestError(f"Thread {thread_id} is not excluded")

    if thread.uses_issue_tracking():
        tracked_issues = await issue_repository.get_issues_by_thread(db, thread.id)
        issues_remaining = apply_thread_issue_tracking_state(
            thread, tracked_issues
        ).issues_remaining
    else:
        issues_remaining = thread.issues_remaining

    if issues_remaining > 0:
        # Append behind every thread the reader already has positioned.
        max_position = await thread_repository.max_queue_position(db, user_id)
        thread.status = "active"
        thread.queue_position = max_position + 1
    else:
        thread.status = "completed"
        thread.queue_position = 0

    # Restoration is a new queue entry, not a continuation of the placement the
    # reader had before removing the series (#3638).
    thread.queue_position_is_manual = False

    # The first renormalize call only acquires the queue lock (it runs before
    # the row is written). Returning the series to the active set changes queue
    # membership, so renumber the survivors again now that the update is
    # staged. The lock is already held, so the second call only renumbers.
    if thread.status == "active":
        await thread_repository.renormalize_queue_positions(db, user_id)

    await db.commit()
    await db.refresh(thread)
    return await thread_to_response(thread, db)


async def reactivate_completed_thread(
    db: AsyncSession, user_id: int, request: ReactivateRequest
) -> ThreadResponse:
    """Reactivate a completed thread by adding more issues.

    Active threads shift back one queue position and the reactivated thread
    takes position 1.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        request: Reactivation request with thread_id and issues_to_add.

    Returns:
        ThreadResponse with reactivated thread details.

    Raises:
        NotFoundError: When the thread does not exist for this user.
        InvalidRequestError: When the thread is not completed or the issue count
            is not positive.
    """
    # Take the queue lock first to prevent deadlocks with concurrent shuffles.
    await thread_repository.renormalize_queue_positions(db, user_id)
    thread = await _require_owned_thread(db, user_id, request.thread_id)
    if thread.status != "completed":
        raise InvalidRequestError(f"Thread {request.thread_id} is not completed")
    if request.issues_to_add <= 0:
        raise InvalidRequestError("Must add at least 1 issue")

    await thread_repository.shift_active_queue_positions(db, user_id)

    if thread.uses_issue_tracking():
        locked_rows = await issue_repository.locked_issue_rows(db, thread.id)
        existing_total = len(locked_rows)
        max_position = max((row[2] for row in locked_rows), default=0)
        max_numeric_issue_number = max(
            (int(row[1]) for row in locked_rows if row[1].isdigit()),
            default=0,
        )

        first_new_issue = None
        for i in range(
            max_numeric_issue_number + 1,
            max_numeric_issue_number + request.issues_to_add + 1,
        ):
            max_position += 1
            new_issue = Issue(
                thread_id=thread.id,
                issue_number=str(i),
                status="unread",
                position=max_position,
            )
            if first_new_issue is None:
                first_new_issue = new_issue
            await issue_repository.add_issue(db, new_issue)

        await db.flush()

        thread.total_issues = existing_total + request.issues_to_add
        thread.reading_progress = "in_progress"
        thread.issues_remaining = request.issues_to_add

        if first_new_issue:
            thread.next_unread_issue_id = first_new_issue.id
    else:
        thread.issues_remaining = request.issues_to_add

    thread.status = "active"
    thread.queue_position = 1
    # Reactivation creates a fresh queue entry and must not inherit a manual
    # placement claim from before the series completed (#3638).
    thread.queue_position_is_manual = False
    await thread_repository.renormalize_queue_positions(db, user_id)
    await db.commit()
    await db.refresh(thread)

    return await thread_to_response(thread, db)


async def set_pending_thread(
    db: AsyncSession, user_id: int, thread_id: int, *, expected_issue_id: int | None = None
) -> RollResponse:
    """Set a thread as pending for rating (manual selection).

    Manual selection sets the pending pointer directly; no random roll is
    performed. A tombstone roll event records the manual selection and any
    snooze entry for the thread is cleared.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread to select.
        expected_issue_id: Optional identity of the offered Issue, to reject stale plan selections.

    Returns:
        RollResponse describing the selected thread.

    Raises:
        NotFoundError: When the thread does not exist for this user.
        InvalidRequestError: When the thread is not active, blocked, or has no issues left.
    """
    thread = await _require_owned_thread(db, user_id, thread_id, for_update=True)
    eligibility = await get_execution_eligibility(db, user_id)

    if thread.status != "active":
        raise InvalidRequestError(f"Thread {thread_id} is not active")

    if eligibility is not None and thread_id not in eligibility.candidate_ids():
        raise InvalidRequestError(f"Thread {thread_id} has no available issue")

    if eligibility is None and thread.is_blocked:
        dependencies = await get_blocking_explanations(thread_id, user_id, db)
        reason = ""
        if dependencies:
            reason = f": {format_blocking_reason(dependencies[0])}"
        raise InvalidRequestError(f"Thread {thread_id} is blocked by a dependency{reason}")

    thread_id_int = thread.id
    thread_title = thread.title
    thread_format = normalize_format_value(thread.format)
    thread_issues = thread.issues_remaining
    thread_position = await display_position(db, thread)
    thread_total_issues = thread.total_issues
    thread_reading_progress = thread.reading_progress
    thread_next_unread_issue_id = thread.next_unread_issue_id

    thread_issue_id = None
    thread_issue_number = None
    if eligibility is not None:
        thread_issue_id = eligibility.threads[thread_id].next_issue_id
        thread_issue_number = eligibility.issue_numbers.get(thread_issue_id)
        thread_issues = eligibility.unread_counts.get(thread_id, 0)
    elif thread.uses_issue_tracking() and thread_next_unread_issue_id:
        next_issue = await issue_repository.get_issue(db, thread_next_unread_issue_id)
        if next_issue:
            thread_issue_id = next_issue.id
            thread_issue_number = next_issue.issue_number

    if thread_issues <= 0:
        raise InvalidRequestError(f"Thread {thread_id} has no issues remaining")

    # A Reading Plan offers a specific Issue, not just its parent series.
    # Enforce that exact offer before writing session state or the manual roll
    # event. If another read advances the frontier, never select its successor.
    if expected_issue_id is not None and thread_issue_id != expected_issue_id:
        raise ConflictError("This issue is no longer next and available. Refresh the reading plan and try again.")

    current_session = await get_or_create(db, user_id=user_id)
    current_session_id = current_session.id
    current_die = await get_current_die(current_session_id, db)

    if eligibility is not None:
        # Read now explicitly clears a current-session snooze. Record that
        # decision so durable backoff and rating see the same unsnooze.
        if thread_id in (current_session.snoozed_thread_ids or []):
            db.add(Event(type="unsnooze", session_id=current_session_id, thread_id=thread_id))
            await db.flush()
        excluded = await derive_effective_roll_excluded_thread_ids(
            db,
            user_id,
            session_skipped_ids=current_session.skipped_thread_ids,
        )
        if thread_id in excluded:
            raise InvalidRequestError(f"Thread {thread_id} is excluded from this reading session")
    else:
        # Legacy execution mode: manual selection also clears a current-session
        # snooze. Record the unsnooze so historical replay sees the boundary
        # state correctly (#4209).
        if thread_id in (current_session.snoozed_thread_ids or []):
            db.add(Event(type="unsnooze", session_id=current_session_id, thread_id=thread_id))
            await db.flush()

    snoozed_ids = (
        list(current_session.snoozed_thread_ids) if current_session.snoozed_thread_ids else []
    )
    snoozed_count = len(snoozed_ids)
    offset = snoozed_count

    result = 0
    event = Event(
        type="roll",
        session_id=current_session_id,
        selected_thread_id=thread_id_int,
        die=current_die,
        result=result,
        selection_method="manual",
        issue_id=thread_issue_id,
        issue_number=thread_issue_number,
    )
    db.add(event)

    current_session.pending_thread_id = thread_id_int
    current_session.pending_thread_updated_at = datetime.now(UTC)

    if eligibility is not None:
        current_session.pending_issue_id = thread_issue_id

    # A manual selection retargets the whole pending pair: a pending issue
    # pinned to a different thread is superseded, never carried over, so the
    # pair always references one thread (issue #3225).
    if current_session.pending_issue_id is not None:
        stale_issue = await issue_repository.get_issue(db, current_session.pending_issue_id)
        if stale_issue is None or stale_issue.thread_id != thread_id_int:
            current_session.pending_issue_id = None

    await require_session_pending_consistent(db, current_session)

    if thread_id_int in snoozed_ids:
        snoozed_ids.remove(thread_id_int)
        current_session.snoozed_thread_ids = snoozed_ids
        offset = len(snoozed_ids)
        snoozed_count = len(snoozed_ids)

    await db.commit()

    return RollResponse(
        thread_id=thread_id_int,
        title=thread_title,
        format=thread_format,
        issues_remaining=thread_issues,
        queue_position=thread_position,
        die_size=current_die,
        result=result,
        offset=offset,
        snoozed_count=snoozed_count,
        issue_id=thread_issue_id,
        issue_number=thread_issue_number,
        next_issue_id=thread_issue_id,
        next_issue_number=thread_issue_number,
        total_issues=thread_total_issues,
        reading_progress=thread_reading_progress,
    )


async def backdate_thread_for_testing(
    db: AsyncSession, user_id: int, thread_id: int, days_ago: int
) -> ThreadResponse:
    """Backdate a thread's last_activity_at for E2E testing.

    Only available when TEST_ENVIRONMENT is set.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread.
        days_ago: Number of days to backdate last_activity_at (1-3650).

    Returns:
        ThreadResponse with updated thread details.

    Raises:
        ForbiddenError: When not running in the test environment.
        NotFoundError: When the thread does not exist for this user.
    """
    if not os.getenv("TEST_ENVIRONMENT"):
        raise ForbiddenError("This endpoint is only available in test environment")

    thread = await _require_owned_thread(db, user_id, thread_id)

    thread.last_activity_at = datetime.now(UTC) - timedelta(days=days_ago)
    await db.commit()
    await db.refresh(thread)

    return await thread_to_response(thread, db)


async def migrate_thread_to_issues(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
    *,
    last_issue_read: int,
    total_issues: int,
) -> ThreadResponse:
    """Migrate an old-style thread to use issue tracking.

    Creates issue records #1 through ``total_issues`` and marks #1 through
    ``last_issue_read`` as read via the model's migration routine.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread to migrate.
        last_issue_read: Highest issue number already read.
        total_issues: Total issues to create.

    Returns:
        ThreadResponse with the migrated thread.

    Raises:
        NotFoundError: When the thread does not exist for this user.
        InvalidRequestError: When the thread already tracks issues or the range is
            inconsistent.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)

    if thread.total_issues is not None:
        raise InvalidRequestError(f"Thread {thread_id} already uses issue tracking")

    if last_issue_read > total_issues:
        raise InvalidRequestError("last_issue_read cannot exceed total_issues")

    await thread.migrate_to_issues(last_issue_read, total_issues, db)

    response = await thread_to_response(thread, db)

    await db.commit()

    return response


async def migrate_thread_to_issues_simple(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
    *,
    issue_number: str,
) -> ThreadResponse:
    """Migrate a legacy thread using the issue the user just rated.

    Infers ``total_issues`` from ``issues_remaining`` and the given issue
    number when the thread has no issues yet, marks every earlier position as
    read, keeps the rated issue unread for the rating flow, and points
    ``next_unread_issue_id`` at it.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread to migrate.
        issue_number: Displayed number of the issue just rated.

    Returns:
        ThreadResponse with the migrated thread.

    Raises:
        NotFoundError: When the thread does not exist for this user.
        InvalidRequestError: When the thread already tracks issues, the issue
            is missing and cannot be created, or the number is non-numeric.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)

    if thread.total_issues is not None:
        raise InvalidRequestError(f"Thread {thread_id} already uses issue tracking")

    current_issue = await issue_repository.find_in_thread_by_number(db, thread_id, issue_number)

    if not current_issue:
        try:
            issue_num_int = int(issue_number)
            total_issues = issue_num_int + max(thread.issues_remaining - 1, 0)

            for i in range(1, total_issues + 1):
                if i < issue_num_int:
                    issue_status = "read"
                    read_at = datetime.now(UTC)
                else:
                    issue_status = "unread"
                    read_at = None

                await issue_repository.add_issue(
                    db,
                    Issue(
                        thread_id=thread.id,
                        issue_number=str(i),
                        status=issue_status,
                        read_at=read_at,
                        position=i,
                    ),
                )

            current_issue = await issue_repository.find_in_thread_by_number(
                db, thread_id, issue_number
            )

            if not current_issue:
                raise InvalidRequestError(
                    f"Failed to create issue '{issue_number}'. Please add it via Edit Thread first."
                )
        except ValueError:
            raise InvalidRequestError(
                f"Non-numeric issue '{issue_number}' not found in thread."
                " Please add it via Edit Thread first."
            ) from None

    all_issues = await issue_repository.issues_ordered(db, thread_id)

    for issue in all_issues:
        if issue.position < current_issue.position:
            if issue.status != "read":
                issue.status = "read"
                issue.read_at = datetime.now(UTC)
        elif issue.position == current_issue.position:
            issue.status = "unread"
            issue.read_at = None

    thread.total_issues = len(all_issues)
    thread.next_unread_issue_id = current_issue.id
    thread.reading_progress = "in_progress"

    response = await thread_to_response(thread, db)

    await db.commit()

    return response


async def set_current_issue(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
    *,
    issue_number: str,
) -> SetCurrentIssueResponse:
    """Atomically correct the current issue for an active owned thread.

    Marks every issue before the target as read, ensures the target is
    unread, updates ``thread.next_unread_issue_id``, and pins
    ``session.pending_issue_id`` so the active roll reflects the corrected
    position immediately.

    Args:
        db: Database session.
        user_id: Owner that must own the thread.
        thread_id: Primary key of the thread whose current issue is corrected.
        issue_number: Displayed number of the target issue.

    Returns:
        SetCurrentIssueResponse with the corrected thread and issue info.

    Raises:
        NotFoundError: When the thread or target issue does not exist for this
            user.
        InvalidRequestError: When the thread is not active or does not use
            issue tracking.
    """
    thread = await _require_owned_thread(db, user_id, thread_id, for_update=True)
    eligibility = await get_execution_eligibility(db, user_id)

    if thread.status != "active":
        raise InvalidRequestError(f"Thread {thread_id} is not active")

    if eligibility is None and not thread.uses_issue_tracking():
        raise InvalidRequestError(f"Thread {thread_id} does not use issue tracking")

    # Session creation/initialization may commit. Resolve it before changing
    # Issue statuses so a later unavailable-selection rejection stays atomic.
    current_session = await get_or_create(db, user_id=user_id)
    await db.refresh(thread)

    target_number = issue_number.strip()

    target_issue = await issue_repository.find_in_thread_by_number(db, thread_id, target_number)

    if not target_issue:
        raise NotFoundError(f"Issue '{target_number}' not found in thread {thread_id}")

    all_issues = await issue_repository.issues_ordered(db, thread_id)

    now = datetime.now(UTC)
    for issue in all_issues:
        if issue.position < target_issue.position:
            if issue.status != "read":
                issue.status = "read"
                issue.read_at = now
        elif issue.position == target_issue.position:
            if issue.status != "unread":
                issue.status = "unread"
                issue.read_at = None

    thread.total_issues = len(all_issues)
    # Defense in depth: the target was resolved inside this thread, and the
    # guard plus fk_threads_frontier_same_thread reject a frontier pointing
    # at any other thread — even one owned by the same reader (issue #3225).
    await require_frontier_in_thread(db, thread_id, target_issue.id)
    thread.next_unread_issue_id = target_issue.id
    thread.reading_progress = "in_progress"
    thread.issues_remaining = await thread.get_issues_remaining(db)

    target_issue_id = target_issue.id
    target_issue_number = target_issue.issue_number

    # Extract attributes before commit so post-commit access never triggers a
    # lazy load (MissingGreenlet rule from AGENTS.md).
    issues_remaining = thread.issues_remaining
    total_issues = thread.total_issues
    reading_progress = thread.reading_progress
    queue_position = await display_position(db, thread)
    thread_title = thread.title
    thread_format = normalize_format_value(thread.format)

    current_session.pending_thread_id = thread_id
    current_session.pending_issue_id = target_issue_id
    current_session.pending_thread_updated_at = now

    await require_session_pending_consistent(db, current_session)

    if eligibility is None:
        await db.commit()
    else:
        await db.flush()
        updated = await get_execution_eligibility(db, user_id)
        if updated is None or updated.threads[thread_id].next_issue_id != target_issue_id:
            raise InvalidRequestError("The corrected issue is not available in the reading order")
        await set_pending_thread(db, user_id, thread_id)

    return SetCurrentIssueResponse(
        thread_id=thread_id,
        title=thread_title,
        format=thread_format,
        issues_remaining=issues_remaining,
        queue_position=queue_position,
        issue_id=target_issue_id,
        issue_number=target_issue_number,
        next_issue_id=target_issue_id,
        next_issue_number=target_issue_number,
        total_issues=total_issues,
        reading_progress=reading_progress,
    )


async def get_thread_comicvine_mapping_health(
    db: AsyncSession,
    user_id: int,
    thread_id: int,
) -> ComicVineMappingHealth:
    """Return the stored ComicVine mapping health for one owned thread.

    Args:
        db: Database session.
        user_id: Owner of the thread.
        thread_id: Thread primary key.

    Returns:
        Derived mapping health projection.
    """
    thread = await _require_owned_thread(db, user_id, thread_id)
    health_map = await thread_repository.fetch_comicvine_mapping_health(db, {thread_id})
    mapping_health = health_map.get(thread_id)
    result = build_comicvine_mapping_health(mapping_health, thread.total_issues)
    if result is None:
        # A thread with no health row still gets a projection rather than a 404,
        # matching the Queue list behaviour for legacy threads.
        # Check if the thread has any issues to determine the appropriate status.
        issues_count = await issue_repository.count_thread_issues(db, thread_id)
        if issues_count > 0:
            # Thread has issues but no mapping health - unresolved status
            result = build_comicvine_mapping_health(
                {
                    "tracked_issue_count": 0,
                    "confirmed_issue_count": 0,
                    "needs_mapping_count": issues_count,
                    "needs_review_count": 0,
                    "metadata_missing_count": 0,
                    "has_issues": True,
                },
                thread.total_issues,
            )
        else:
            # Thread has no issues - not_applicable status
            result = build_comicvine_mapping_health(
                {
                    "tracked_issue_count": 0,
                    "confirmed_issue_count": 0,
                    "needs_mapping_count": 0,
                    "needs_review_count": 0,
                    "metadata_missing_count": 0,
                    "has_issues": False,
                },
                thread.total_issues,
            )
    assert result is not None
    return result
