"""Read-only ComicVine hydration planning for existing ComicPile issues."""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cbl_ingest import parse_cbl_mirror
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from comic_pile.local_comicvine import LocalComicVineResult

HydrationStatus = Literal["matched", "local-miss", "unresolved"]


class ComicVineSnapshotReader(Protocol):
    """Read-only ComicVine snapshot contract used by the hydrator."""

    path: Path | None

    @property
    def available(self) -> bool:
        """Return whether snapshot data can be read."""
        ...

    def get_issue(self, issue_id: int) -> LocalComicVineResult | None:
        """Return one local ComicVine issue by provider ID.

        Args:
            issue_id: ComicVine provider issue ID.

        Returns:
            The normalized local snapshot row when present, otherwise None.
        """
        ...

    def get_volume_issues(self, volume_id: int) -> list[LocalComicVineResult]:
        """Return locally cached issues for one ComicVine volume."""
        ...

    def sync_metadata(self) -> dict[str, object]:
        """Return snapshot freshness metadata.

        Returns:
            JSON-compatible snapshot synchronization metadata.
        """
        ...


@dataclass(frozen=True)
class HydrationTarget:
    """One user-owned ComicPile issue considered for ComicVine hydration."""

    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    position: int
    comicvine_issue_id: int | None = None


@dataclass(frozen=True)
class VolumeSegment:
    """Explicit provider-volume evidence for one contiguous slice of a ComicPile thread."""

    thread_id: int
    start_position: int
    end_position: int
    comicvine_volume_id: int

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> VolumeSegment:
        """Parse and validate one JSON segment declaration.

        Args:
            value: JSON-compatible mapping describing a thread slice and ComicVine volume.

        Returns:
            Validated segment declaration.

        Raises:
            ValueError: If required integer fields are absent or invalid.
        """
        fields: dict[str, int] = {}
        for name in ("thread_id", "start_position", "end_position", "comicvine_volume_id"):
            raw = value.get(name)
            if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
                raise ValueError(f"segment {name} must be a positive integer")
            fields[name] = raw
        if fields["end_position"] < fields["start_position"]:
            raise ValueError("segment end_position must be >= start_position")
        return cls(**fields)


@dataclass(frozen=True)
class HydrationResult:
    """Machine-readable report row for one hydration target."""

    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    position: int
    status: HydrationStatus
    comicvine_issue_id: int | None
    provenance: str | None
    detail: str

    def to_dict(self) -> dict[str, object]:
        """Serialize the result without leaking provider credentials.

        Returns:
            JSON-compatible report data.
        """
        return asdict(self)


async def enumerate_user_issues(
    db: AsyncSession,
    *,
    user_id: int,
    include_test_threads: bool = False,
) -> list[HydrationTarget]:
    """Enumerate user-owned issues and reuse confirmed ComicVine identities.

    This query is intentionally read-only. It does not modify reading progress,
    continuity, ratings, threads, issues, or external identity mappings.

    Args:
        db: Async database session.
        user_id: ComicPile user whose issues should be inspected.
        include_test_threads: Include threads marked as test data when true.

    Returns:
        Deterministically ordered hydration targets.
    """
    issue_query = (
        select(Issue, Thread)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
        .order_by(Thread.queue_position, Thread.id, Issue.position, Issue.id)
    )
    if not include_test_threads:
        issue_query = issue_query.where(Thread.is_test.is_(False))

    rows = (await db.execute(issue_query)).all()
    issue_ids = [issue.id for issue, _thread in rows]
    confirmed_ids_by_issue: dict[int, set[int]] = defaultdict(set)
    if issue_ids:
        mapping_query = (
            select(IssueExternalIdentityMapping.issue_id, ExternalIdentity.external_id)
            .join(
                ExternalIdentity,
                ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
            )
            .where(
                IssueExternalIdentityMapping.issue_id.in_(issue_ids),
                IssueExternalIdentityMapping.status == "confirmed",
                ExternalIdentity.provider == "comicvine",
                ExternalIdentity.entity_type == "issue",
            )
        )
        for issue_id, external_id in (await db.execute(mapping_query)).all():
            try:
                confirmed_ids_by_issue[issue_id].add(int(external_id))
            except (TypeError, ValueError):
                continue

    confirmed_by_issue = {
        issue_id: next(iter(external_ids))
        for issue_id, external_ids in confirmed_ids_by_issue.items()
        if len(external_ids) == 1
    }
    return [
        HydrationTarget(
            issue_id=issue.id,
            thread_id=thread.id,
            thread_title=thread.title,
            issue_number=issue.issue_number,
            position=issue.position,
            comicvine_issue_id=confirmed_by_issue.get(issue.id),
        )
        for issue, thread in rows
    ]


def _normalized_cbl_key(value: str) -> str:
    """Normalize exact CBL matching text without introducing fuzzy equivalence."""
    return " ".join(value.strip().casefold().split()).removeprefix("#").strip()


async def apply_cbl_issue_identities(
    targets: list[HydrationTarget],
    mirror_path: str | Path,
) -> list[HydrationTarget]:
    """Fill unresolved targets from unique exact CBL embedded ComicVine issue IDs.

    Existing confirmed database mappings remain authoritative. CBL evidence is only applied
    when the normalized CBL series title and issue label exactly match the ComicPile target
    and every matching CBL occurrence with an embedded ComicVine issue ID agrees on one ID.
    Conflicting or malformed CBL evidence stays unresolved.

    Args:
        targets: Ordered ComicPile hydration targets.
        mirror_path: Root directory containing CBL reading-list files.

    Returns:
        Targets with safe exact CBL issue identities filled where uniquely supported.
    """
    root = Path(mirror_path)
    parsed_lists, _failures = await asyncio.to_thread(parse_cbl_mirror, root)
    ids_by_key: dict[tuple[str, str], set[int]] = defaultdict(set)
    for reading_list in parsed_lists:
        for book in reading_list.books:
            if book.comicvine_issue_id is None:
                continue
            try:
                issue_id = int(book.comicvine_issue_id)
            except ValueError:
                continue
            if issue_id <= 0:
                continue
            key = (
                _normalized_cbl_key(book.series),
                _normalized_cbl_key(book.issue_number),
            )
            ids_by_key[key].add(issue_id)

    resolved: list[HydrationTarget] = []
    for target in targets:
        if target.comicvine_issue_id is not None:
            resolved.append(target)
            continue
        key = (
            _normalized_cbl_key(target.thread_title),
            _normalized_cbl_key(target.issue_number),
        )
        matches = ids_by_key.get(key, set())
        if len(matches) == 1:
            resolved.append(replace(target, comicvine_issue_id=next(iter(matches))))
        else:
            resolved.append(target)
    return resolved


def load_volume_segments(path: str | Path) -> list[VolumeSegment]:
    """Load deterministic issue-level volume segments from JSON.

    The file is intentionally explicit evidence. Segments scope a provider volume to a
    position range inside one ComicPile reading thread; they never declare that an entire
    thread is one external volume.

    Args:
        path: JSON file containing either a segment list or {"segments": [...]}.

    Returns:
        Validated segments sorted by thread and position.

    Raises:
        ValueError: If the JSON shape is invalid or segments overlap within a thread.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw.get("segments") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("segment map must be a JSON list or an object containing 'segments'")

    segments = [VolumeSegment.from_dict(item) for item in items if isinstance(item, dict)]
    if len(segments) != len(items):
        raise ValueError("every segment entry must be a JSON object")
    segments.sort(key=lambda segment: (segment.thread_id, segment.start_position, segment.end_position))

    previous_by_thread: dict[int, VolumeSegment] = {}
    for segment in segments:
        previous = previous_by_thread.get(segment.thread_id)
        if previous is not None and segment.start_position <= previous.end_position:
            raise ValueError(f"overlapping volume segments for thread {segment.thread_id}")
        previous_by_thread[segment.thread_id] = segment
    return segments


async def apply_local_volume_segments(
    targets: list[HydrationTarget],
    snapshot: ComicVineSnapshotReader,
    segments: list[VolumeSegment],
) -> list[HydrationTarget]:
    """Resolve unresolved issue identities from explicit per-thread volume segments.

    A segment is only an optimization/evidence boundary. Each issue must still match exactly
    one provider issue by number or provider issue name inside that volume. Existing confirmed
    issue identities always win, and ambiguous/missing labels remain unresolved.

    Args:
        targets: Ordered ComicPile hydration targets.
        snapshot: Read-only local ComicVine snapshot.
        segments: Explicit issue-level volume segment declarations.

    Returns:
        Targets with safe local identities filled where uniquely resolved.
    """
    segments_by_thread: dict[int, list[VolumeSegment]] = defaultdict(list)
    for segment in segments:
        segments_by_thread[segment.thread_id].append(segment)

    roster_cache: dict[int, dict[str, set[int]]] = {}
    resolved: list[HydrationTarget] = []
    for target in targets:
        if target.comicvine_issue_id is not None:
            resolved.append(target)
            continue
        segment = next(
            (
                candidate
                for candidate in segments_by_thread.get(target.thread_id, [])
                if candidate.start_position <= target.position <= candidate.end_position
            ),
            None,
        )
        if segment is None:
            resolved.append(target)
            continue

        if segment.comicvine_volume_id not in roster_cache:
            rows = await asyncio.to_thread(snapshot.get_volume_issues, segment.comicvine_volume_id)
            labels: dict[str, set[int]] = defaultdict(set)
            for row in rows:
                issue_id = row.data.get("id")
                if not isinstance(issue_id, int) or isinstance(issue_id, bool):
                    continue
                for raw_label in (row.data.get("issue_number"), row.data.get("name")):
                    if raw_label is None:
                        continue
                    label = str(raw_label).strip().casefold().removeprefix("#").strip()
                    if label:
                        labels[label].add(issue_id)
            roster_cache[segment.comicvine_volume_id] = labels

        expected = target.issue_number.strip().casefold().removeprefix("#").strip()
        matches = roster_cache[segment.comicvine_volume_id].get(expected, set())
        if len(matches) == 1:
            resolved.append(replace(target, comicvine_issue_id=next(iter(matches))))
        else:
            resolved.append(target)
    return resolved


async def inspect_local_snapshot(
    target: HydrationTarget,
    snapshot: ComicVineSnapshotReader,
) -> HydrationResult:
    """Resolve one target from confirmed identity plus the local snapshot only.

    A confirmed ComicVine issue ID is authoritative identity evidence. A local
    snapshot miss is reported rather than converted into a guessed mapping. Live
    provider fallback is deliberately left to the endpoint-budgeted client from
    #1019 so this foundation remains safe and restart-friendly.

    SQLite snapshot reads are moved to a worker thread so the asynchronous CLI
    does not block its event loop while reading the developer-local snapshot.

    Args:
        target: ComicPile issue to inspect.
        snapshot: Read-only local ComicVine snapshot.

    Returns:
        A report row describing the local resolution state.
    """
    if target.comicvine_issue_id is None:
        return HydrationResult(
            issue_id=target.issue_id,
            thread_id=target.thread_id,
            thread_title=target.thread_title,
            issue_number=target.issue_number,
            position=target.position,
            status="unresolved",
            comicvine_issue_id=None,
            provenance=None,
            detail="No confirmed ComicVine issue identity is available yet.",
        )

    local = await asyncio.to_thread(snapshot.get_issue, target.comicvine_issue_id)
    if local is None:
        return HydrationResult(
            issue_id=target.issue_id,
            thread_id=target.thread_id,
            thread_title=target.thread_title,
            issue_number=target.issue_number,
            position=target.position,
            status="local-miss",
            comicvine_issue_id=target.comicvine_issue_id,
            provenance="comicvine-local-sqlite",
            detail="Confirmed identity is absent from the configured local snapshot.",
        )
    if not local.complete:
        return HydrationResult(
            issue_id=target.issue_id,
            thread_id=target.thread_id,
            thread_title=target.thread_title,
            issue_number=target.issue_number,
            position=target.position,
            status="local-miss",
            comicvine_issue_id=target.comicvine_issue_id,
            provenance=local.provenance,
            detail="Confirmed identity exists locally, but required hydration data is missing.",
        )

    provider_issue_number = str(local.data.get("issue_number", "")).strip()
    detail = "Confirmed identity resolved from the local ComicVine snapshot."
    if provider_issue_number and provider_issue_number != target.issue_number:
        detail = (
            "Confirmed identity resolved; provider issue number differs from the "
            "ComicPile label, so the mapping is preserved instead of guessed by number."
        )
    return HydrationResult(
        issue_id=target.issue_id,
        thread_id=target.thread_id,
        thread_title=target.thread_title,
        issue_number=target.issue_number,
        position=target.position,
        status="matched",
        comicvine_issue_id=target.comicvine_issue_id,
        provenance=local.provenance,
        detail=detail,
    )


async def build_report(
    targets: list[HydrationTarget],
    snapshot: ComicVineSnapshotReader,
) -> dict[str, object]:
    """Build a deterministic report suitable for resumable hydrator handoff.

    Args:
        targets: Ordered ComicPile issues to inspect.
        snapshot: Read-only local ComicVine snapshot.

    Returns:
        Summary counts, snapshot metadata, and per-issue results.
    """
    results = [await inspect_local_snapshot(target, snapshot) for target in targets]
    counts: dict[str, int] = {"matched": 0, "local-miss": 0, "unresolved": 0}
    for result in results:
        counts[result.status] += 1
    sync_metadata = await asyncio.to_thread(snapshot.sync_metadata)
    return {
        "summary": {"total": len(results), **counts},
        "snapshot": {
            "path": str(snapshot.path) if snapshot.path is not None else None,
            "available": snapshot.available,
            "sync_metadata": sync_metadata,
        },
        "issues": [result.to_dict() for result in results],
    }


def write_report(report: dict[str, object], output_path: str | Path) -> None:
    """Write a hydration report atomically enough for restart-safe CLI use.

    Args:
        report: JSON-compatible hydration report.
        output_path: Destination file path.
    """
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(report, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
