"""Local ComicVine candidate discovery for confidence-aware identity repair."""

from __future__ import annotations

from datetime import datetime

from comic_pile.comicvine_identity_repair import (
    ComicVineCandidate,
    ComicVineRepairContext,
    normalize_issue_label,
)
from comic_pile.local_comicvine import LocalComicVineSnapshot


def snapshot_sync_time(snapshot: LocalComicVineSnapshot) -> datetime | None:
    """Return the newest parseable local snapshot sync timestamp."""
    timestamps: list[datetime] = []
    for row in snapshot.sync_metadata().values():
        if not isinstance(row, dict):
            continue
        value = row.get("value")
        if not isinstance(value, str):
            continue
        try:
            timestamps.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            continue
    return max(timestamps) if timestamps else None


def _publisher_name(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        name = value.get("name")
        return name.strip() if isinstance(name, str) and name.strip() else None
    return None


def _integer(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _segment_for_labels(
    thread_issue_labels: list[str],
    target_label: str,
    provider_labels: set[str],
) -> tuple[str | None, str | None]:
    normalized_thread = [normalize_issue_label(label) for label in thread_issue_labels]
    normalized_target = normalize_issue_label(target_label)
    try:
        target_index = normalized_thread.index(normalized_target)
    except ValueError:
        return None, None

    start = target_index
    while start > 0 and normalized_thread[start - 1] in provider_labels:
        start -= 1
    end = target_index
    while end + 1 < len(normalized_thread) and normalized_thread[end + 1] in provider_labels:
        end += 1
    return thread_issue_labels[start], thread_issue_labels[end]


def discover_local_candidates(
    snapshot: LocalComicVineSnapshot,
    context: ComicVineRepairContext,
    *,
    thread_issue_labels: list[str],
    limit: int = 20,
) -> list[ComicVineCandidate]:
    """Discover issue-level candidates from local FTS plus exact volume issue validation."""
    expected = normalize_issue_label(context.issue_label)
    candidates: list[ComicVineCandidate] = []
    seen_issue_ids: set[int] = set()

    for search_hit in snapshot.search_volumes(context.title, limit=limit):
        volume_id = _integer(search_hit.data.get("id"))
        if volume_id is None:
            continue
        volume = snapshot.get_volume(volume_id)
        if volume is None:
            continue
        issues = snapshot.get_volume_issues(volume_id)
        provider_labels = {
            label
            for issue in issues
            for label in (
                normalize_issue_label(
                    str(issue.data["issue_number"])
                    if issue.data.get("issue_number") is not None
                    else None
                ),
                normalize_issue_label(
                    issue.data.get("name") if isinstance(issue.data.get("name"), str) else None
                ),
            )
            if label
        }
        segment_start, segment_end = _segment_for_labels(
            thread_issue_labels,
            context.issue_label,
            provider_labels,
        )

        for issue in issues:
            issue_id = _integer(issue.data.get("id"))
            if issue_id is None or issue_id in seen_issue_ids:
                continue
            issue_number = issue.data.get("issue_number")
            issue_name = issue.data.get("name")
            number_text = str(issue_number) if issue_number is not None else None
            name_text = issue_name if isinstance(issue_name, str) else None
            if expected not in {
                normalize_issue_label(number_text),
                normalize_issue_label(name_text),
            }:
                continue
            seen_issue_ids.add(issue_id)
            volume_name = volume.data.get("name")
            if not isinstance(volume_name, str) or not volume_name:
                continue
            candidates.append(
                ComicVineCandidate(
                    issue_id=issue_id,
                    volume_id=volume_id,
                    volume_name=volume_name,
                    issue_number=number_text,
                    issue_name=name_text,
                    publisher=_publisher_name(volume.data.get("publisher")),
                    start_year=_integer(volume.data.get("start_year")),
                    previous_issue_exists=(
                        context.previous_issue_label is not None
                        and normalize_issue_label(context.previous_issue_label) in provider_labels
                    ),
                    next_issue_exists=(
                        context.next_issue_label is not None
                        and normalize_issue_label(context.next_issue_label) in provider_labels
                    ),
                    segment_start=segment_start,
                    segment_end=segment_end,
                )
            )

    return sorted(candidates, key=lambda candidate: (candidate.volume_id, candidate.issue_id))
