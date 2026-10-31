"""Read-only prospective reading graph for adding or updating a CBL selection.

The preview is a projection of the one canonical Option E evaluator and cycle
validator. It builds the graph the reader *would* get, using the exact same
``ReadingSnapshot`` / ``evaluate`` / ``validate_reading_constraints`` code that
Roll, Queue and saved-list writes execute. It never persists list membership,
issue status, or an overlap decision.

Series are identified by their exact Comic Vine volume key. A Thread that
cannot be resolved to one unambiguous volume is shown under a distinct
``unidentified-thread:<id>`` key and never produces an overlap question, so a
same-titled other volume can never inherit the reader's answer.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256

from fastapi import HTTPException, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.repositories import reading_graph_preview_repository as preview_repository
from app.repositories import reading_list_authoring_repository as authoring
from app.schemas.reading_graph_preview import (
    ReadingGraphBlocker,
    ReadingGraphChoiceEffect,
    ReadingGraphChoiceId,
    ReadingGraphCycleError,
    ReadingGraphIssueReference,
    ReadingGraphOverlap,
    ReadingGraphPreview,
    ReadingGraphPreviewRequest,
    ReadingGraphSeriesNode,
    ReadingGraphSeriesReference,
)
from app.services.cbl_reconciliation import reconcile_cbl_source_list
from app.services.cbl_source_service import get_cbl_source_list_preview
from app.services.reading_blocker_projection import (
    DescribedBlockerGate,
    describe_blocker_gates,
)
from app.services.reading_list_cycle_validator import (
    ReadingCycleError,
    validate_reading_constraints,
)
from app.services.reading_list_evaluator import (
    ReadingIssue,
    ReadingList,
    ReadingListEntry,
    ReadingPrerequisite,
    ReadingSnapshot,
    ReadingThread,
    SeriesOverlapDecision,
    ThreadEligibility,
    evaluate,
)


@dataclass(frozen=True, slots=True)
class _IssueMeta:
    """Owned Issue facts used to label and group the prospective graph."""

    issue_id: int
    thread_id: int
    issue_number: str
    position: int
    status: str


@dataclass(frozen=True, slots=True)
class _GraphContext:
    """Immutable graph inputs shared by the preview and its choice effects."""

    snapshot: ReadingSnapshot
    proposed_list_id: int
    graph_thread_ids: frozenset[int]
    graph_issue_ids: frozenset[int]
    issue_meta: Mapping[int, _IssueMeta]
    volume_by_issue: Mapping[int, str | None]
    series_refs: Mapping[str, ReadingGraphSeriesReference]
    list_names: Mapping[int, str]
    thread_names: Mapping[int, str]


def _http_error(code: str, message: str, *, status_code: int) -> HTTPException:
    """Build a structured preview error without mutating reader state."""
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _volume_key(provider: object, external_id: object) -> str | None:
    """Return a canonical Comic Vine volume key from source reconciliation data."""
    if provider is None or external_id is None:
        return None
    return preview_repository.canonical_volume_key(str(provider), str(external_id))


def _overlap_identity(continuing_volume_id: str, waiting_volume_id: str) -> str:
    """Return a stable, opaque identity for one exact volume pair."""
    digest = sha256(f"{continuing_volume_id}\0{waiting_volume_id}".encode()).hexdigest()
    return f"overlap-{digest[:24]}"


def _pair_sort_key(pair: tuple[str, str]) -> tuple[str, str]:
    """Order volume pairs deterministically regardless of issue discovery order."""
    return pair


def _snapshot_lists(
    *,
    owned_lists: Sequence[CustomCBLList],
    entries_by_list: Mapping[int, Sequence[CustomCBLEntry]],
    proposed_list_id: int,
    proposed_mode: str,
    proposed_entries: tuple[ReadingListEntry, ...],
    proposed_name: str,
    decisions: tuple[SeriesOverlapDecision, ...],
) -> tuple[ReadingList, ...]:
    """Build the complete list tuple with the prospective list included once."""
    lists: list[ReadingList] = []
    for row in sorted(owned_lists, key=lambda value: value.id):
        if row.id == proposed_list_id:
            continue
        lists.append(
            ReadingList(
                row.id,
                row.mode,
                tuple(
                    ReadingListEntry(entry.issue_id, entry.gate, entry.skipped)
                    for entry in entries_by_list.get(row.id, ())
                ),
                row.name,
            )
        )
    lists.append(
        ReadingList(
            proposed_list_id,
            proposed_mode,
            proposed_entries,
            proposed_name,
            decisions,
        )
    )
    return tuple(lists)


def _build_snapshot(
    context: _GraphContext,
    decisions: tuple[SeriesOverlapDecision, ...],
    *,
    owned_lists: Sequence[CustomCBLList],
    entries_by_list: Mapping[int, Sequence[CustomCBLEntry]],
    proposed_mode: str,
    proposed_entries: tuple[ReadingListEntry, ...],
    proposed_name: str,
) -> ReadingSnapshot:
    """Rebuild the same owner snapshot with a different overlap decision set."""
    return ReadingSnapshot(
        user_id=context.snapshot.user_id,
        threads=context.snapshot.threads,
        issues=context.snapshot.issues,
        lists=_snapshot_lists(
            owned_lists=owned_lists,
            entries_by_list=entries_by_list,
            proposed_list_id=context.proposed_list_id,
            proposed_mode=proposed_mode,
            proposed_entries=proposed_entries,
            proposed_name=proposed_name,
            decisions=decisions,
        ),
        prerequisites=context.snapshot.prerequisites,
        excluded_issue_ids=context.snapshot.excluded_issue_ids,
    )


def _decisions(
    chosen: Mapping[tuple[str, str], ReadingGraphChoiceId],
) -> tuple[SeriesOverlapDecision, ...]:
    """Translate reader answers into evaluator overlap decisions."""
    return tuple(
        SeriesOverlapDecision(continuing, waiting)
        for (continuing, waiting), choice in sorted(chosen.items(), key=lambda item: item[0])
        if choice == "continue_series"
    )


def _expand_graph_threads(
    snapshot: ReadingSnapshot,
    seed_thread_ids: Collection[int],
    issue_meta: Mapping[int, _IssueMeta],
) -> frozenset[int]:
    """Follow every active blocker until the graph names all relevant series."""
    thread_ids = set(seed_thread_ids)
    eligibility = evaluate(snapshot)
    while True:
        discovered: set[int] = set()
        for thread_id in thread_ids:
            state = eligibility.get(thread_id)
            if state is None:
                continue
            for blocker in state.blockers:
                for issue_id in blocker.waiting_on_issue_ids:
                    meta = issue_meta.get(issue_id)
                    if meta is not None:
                        discovered.add(meta.thread_id)
        new_thread_ids = discovered - thread_ids
        if not new_thread_ids:
            break
        thread_ids.update(new_thread_ids)
    return frozenset(thread_ids)


def _series_reference(
    volume_id: str | None,
    thread_id: int,
    *,
    thread_names: Mapping[int, str],
    source_names: Mapping[str, tuple[str, int | None]],
    volume_years: Mapping[str, int],
) -> ReadingGraphSeriesReference:
    """Return the reader-facing identity of one graph series node."""
    if volume_id is None:
        key = f"unidentified-thread:{thread_id}"
        return ReadingGraphSeriesReference(
            comicvine_volume_id=key,
            series_name=thread_names.get(thread_id) or f"Series {thread_id}",
            year=None,
        )
    source_name, source_year = source_names.get(volume_id, ("", None))
    return ReadingGraphSeriesReference(
        comicvine_volume_id=volume_id,
        series_name=source_name or thread_names.get(thread_id) or volume_id,
        year=source_year if source_year is not None else volume_years.get(volume_id),
    )


@dataclass(slots=True)
class _SeriesAggregate:
    """Mutable accumulation before one exact-volume series node is emitted."""

    thread_id: int
    volume_id: str | None
    unread: int = 0
    rollable: set[int] = field(default_factory=set)
    waiting: set[int] = field(default_factory=set)
    waits_for: set[int] = field(default_factory=set)


def _series_nodes(
    context: _GraphContext,
    eligibility: Mapping[int, ThreadEligibility],
) -> list[ReadingGraphSeriesNode]:
    """Project evaluator state onto exact-volume series nodes."""
    active_thread_ids = {
        thread.thread_id for thread in context.snapshot.threads if thread.status == "active"
    }
    blocker_thread_ids: set[int] = set()
    for state in eligibility.values():
        for blocker in state.blockers:
            for issue_id in blocker.waiting_on_issue_ids:
                meta = context.issue_meta.get(issue_id)
                if meta is not None:
                    blocker_thread_ids.add(meta.thread_id)
    excluded = context.snapshot.excluded_issue_ids
    volume_by_thread = {
        thread.thread_id: thread.comicvine_volume_id for thread in context.snapshot.threads
    }
    grouped: dict[str, _SeriesAggregate] = {}
    for thread_id in sorted(context.graph_thread_ids):
        if thread_id not in active_thread_ids and thread_id not in blocker_thread_ids:
            continue
        volume_id = volume_by_thread.get(thread_id)
        node_key = volume_id or f"unidentified-thread:{thread_id}"
        unread_ids = sorted(
            issue_id
            for issue_id, meta in context.issue_meta.items()
            if meta.thread_id == thread_id
            and meta.issue_id in context.graph_issue_ids
            and meta.status != "read"
            and issue_id not in excluded
        )
        state = eligibility.get(thread_id)
        rollable: set[int] = set()
        waits_for: set[int] = set()
        if (
            state is not None
            and state.eligible
            and state.next_issue_id is not None
            and state.next_issue_id in context.graph_issue_ids
        ):
            rollable.add(state.next_issue_id)
        if state is not None and state.next_issue_id is not None:
            for blocker in state.blockers:
                for issue_id in blocker.waiting_on_issue_ids:
                    meta = context.issue_meta.get(issue_id)
                    if meta is not None and meta.thread_id != thread_id:
                        waits_for.add(issue_id)
        aggregate = grouped.setdefault(
            node_key, _SeriesAggregate(thread_id=thread_id, volume_id=volume_id)
        )
        aggregate.unread += len(unread_ids)
        aggregate.rollable.update(issue_id for issue_id in unread_ids if issue_id in rollable)
        aggregate.waiting.update(issue_id for issue_id in unread_ids if issue_id not in rollable)
        aggregate.waits_for.update(
            issue_id
            for issue_id in waits_for
            if issue_id in context.graph_issue_ids
            and context.issue_meta[issue_id].status != "read"
            and issue_id not in excluded
        )

    nodes: list[ReadingGraphSeriesNode] = []
    for node_key, aggregate in grouped.items():
        reference = context.series_refs.get(node_key)
        if reference is None:
            reference = ReadingGraphSeriesReference(
                comicvine_volume_id=node_key,
                series_name=context.thread_names.get(
                    aggregate.thread_id, f"Series {aggregate.thread_id}"
                ),
                year=None,
            )
        if aggregate.rollable and aggregate.waiting:
            node_state = "mixed"
        elif aggregate.rollable:
            node_state = "continues"
        else:
            node_state = "waits"
        nodes.append(
            ReadingGraphSeriesNode(
                comicvine_volume_id=reference.comicvine_volume_id,
                series_name=reference.series_name,
                year=reference.year,
                state=node_state,
                unread_count=aggregate.unread,
                rollable_count=len(aggregate.rollable),
                waiting_count=len(aggregate.waiting),
                waits_for_issue_ids=sorted(aggregate.waits_for),
            )
        )
    return sorted(
        nodes,
        key=lambda node: (node.series_name.casefold(), node.year or 0, node.comicvine_volume_id),
    )


def _blocker_explanation(
    gate: DescribedBlockerGate,
    *,
    list_names: Mapping[int, str],
    issue_labels: Mapping[int, str],
) -> str:
    """Name one restriction with its actual list/prerequisite authority.

    A gate whose Issues were already described by an earlier gate names only its
    own rule, so the preview keeps every authority without repeating an Issue.
    """
    blocker = gate.blocker
    if blocker.kind == "prerequisite":
        label = (
            "Reader prerequisite" if blocker.origin == "reader" else "Converted prerequisite"
        )
    else:
        kind = {
            "strict_order": "Strict order",
            "hold": "Hold",
            "after_previous": "Wait for previous",
        }[blocker.kind]
        label = f"{kind} in {list_names.get(blocker.list_id, 'Reading List')}"
    if not gate.described_issue_ids:
        return f"Also gated by {label}."
    waiting = ", ".join(
        issue_labels.get(issue_id, f"Issue {issue_id}")
        for issue_id in gate.described_issue_ids
    )
    return f"{label}: waiting on {waiting}"


def _issue_label(context: _GraphContext, issue_id: int) -> str:
    """Return the reader-facing ``Series #Number`` label for one issue."""
    meta = context.issue_meta[issue_id]
    reference = context.series_refs.get(context.volume_by_issue.get(issue_id) or "")
    series_name = (
        reference.series_name
        if reference is not None
        else context.thread_names.get(meta.thread_id, f"Series {meta.thread_id}")
    )
    return f"{series_name} #{meta.issue_number}"


def _issue_references(
    context: _GraphContext,
    eligibility: Mapping[int, ThreadEligibility],
) -> list[ReadingGraphIssueReference]:
    """Build the issue directory with active blockers for each current frontier."""
    labels = {issue_id: _issue_label(context, issue_id) for issue_id in context.issue_meta}
    references: list[ReadingGraphIssueReference] = []
    for issue_id in sorted(
        context.graph_issue_ids,
        key=lambda value: (
            context.issue_meta[value].position,
            context.issue_meta[value].thread_id,
            value,
        ),
    ):
        meta = context.issue_meta[issue_id]
        reference = context.series_refs.get(context.volume_by_issue.get(issue_id) or "")
        series_name = (
            reference.series_name
            if reference is not None
            else context.thread_names.get(meta.thread_id, f"Series {meta.thread_id}")
        )
        blockers: list[ReadingGraphBlocker] = []
        state = eligibility.get(meta.thread_id)
        if state is not None and state.next_issue_id == issue_id:
            blockers = [
                ReadingGraphBlocker(
                    kind=gate.blocker.kind,
                    list_id=gate.blocker.list_id,
                    waiting_on_issue_ids=list(gate.described_issue_ids),
                    gate_issue_id=gate.blocker.gate_issue_id,
                    explanation=_blocker_explanation(
                        gate, list_names=context.list_names, issue_labels=labels
                    ),
                )
                for gate in describe_blocker_gates(state.blockers)
            ]
        references.append(
            ReadingGraphIssueReference(
                issue_id=issue_id,
                series_name=series_name,
                issue_number=meta.issue_number,
                comicvine_volume_id=context.volume_by_issue.get(issue_id),
                blockers=blockers,
            )
        )
    return references


def _cycle_errors(
    snapshot: ReadingSnapshot,
    *,
    list_names: Mapping[int, str],
    thread_names: Mapping[int, str],
    issue_labels: Mapping[int, str],
) -> list[ReadingGraphCycleError]:
    """Return the validator's explanation of an invalid proposed graph."""
    try:
        validate_reading_constraints(
            snapshot,
            list_names=dict(list_names),
            thread_names=dict(thread_names),
        )
    except ReadingCycleError as error:
        path = " -> ".join(
            f"{issue_labels.get(edge.source_issue_id, f'Issue {edge.source_issue_id}')}"
            f" --[{edge.origin}]--> "
            f"{issue_labels.get(edge.target_issue_id, f'Issue {edge.target_issue_id}')}"
            for edge in error.edges
        )
        return [
            ReadingGraphCycleError(
                code="reading_constraint_cycle",
                message=f"Reading constraint cycle: {path}",
            )
        ]
    return []


def _rollable_ids(
    context: _GraphContext, eligibility: Mapping[int, ThreadEligibility]
) -> list[int]:
    """Return the exact graph issues a Roll caller may offer now."""
    return sorted(
        state.next_issue_id
        for state in eligibility.values()
        if state.eligible
        and state.next_issue_id is not None
        and state.next_issue_id in context.graph_issue_ids
    )


def _waiting_ids(
    context: _GraphContext,
    eligibility: Mapping[int, ThreadEligibility],
) -> list[int]:
    """Return unread graph issues that cannot be rolled right now."""
    rollable = set(_rollable_ids(context, eligibility))
    return sorted(
        issue_id
        for issue_id, meta in context.issue_meta.items()
        if issue_id in context.graph_issue_ids
        and meta.status != "read"
        and issue_id not in context.snapshot.excluded_issue_ids
        and issue_id not in rollable
    )


def _choice_effect(
    context: _GraphContext,
    *,
    choice: ReadingGraphChoiceId,
    decisions: tuple[SeriesOverlapDecision, ...],
    continuing: ReadingGraphSeriesReference,
    waiting: ReadingGraphSeriesReference,
    owned_lists: Sequence[CustomCBLList],
    entries_by_list: Mapping[int, Sequence[CustomCBLEntry]],
    proposed_mode: str,
    proposed_entries: tuple[ReadingListEntry, ...],
    proposed_name: str,
) -> ReadingGraphChoiceEffect:
    """Evaluate one answer with the exact canonical evaluator."""
    snapshot = _build_snapshot(
        context,
        decisions,
        owned_lists=owned_lists,
        entries_by_list=entries_by_list,
        proposed_mode=proposed_mode,
        proposed_entries=proposed_entries,
        proposed_name=proposed_name,
    )
    eligibility = evaluate(snapshot)
    if choice == "continue_series":
        label = f"Let {continuing.series_name} continue; {waiting.series_name} waits"
        detail = (
            f"Removes the ordering restriction between {continuing.series_name} and "
            f"{waiting.series_name}; other prerequisites and restrictions still apply."
        )
    else:
        label = "Keep the full chosen order"
        detail = (
            f"{continuing.series_name} waits for every earlier unread "
            f"{waiting.series_name} comic before it continues."
        )
    return ReadingGraphChoiceEffect(
        choice=choice,
        label=label,
        detail=detail,
        rollable_issue_ids=_rollable_ids(context, eligibility),
        waiting_issue_ids=_waiting_ids(context, eligibility),
        series=_series_nodes(context, eligibility),
    )


async def preview_reading_graph(
    db: AsyncSession,
    *,
    user_id: int,
    source_list_id: int,
    request: ReadingGraphPreviewRequest,
) -> ReadingGraphPreview:
    """Return the prospective graph for a CBL selection without writing anything.

    Args:
        db: Current read transaction. The preview never flushes a reader write.
        user_id: Authenticated owner whose existing lists are part of the graph.
        source_list_id: Shared CBL source list being adopted or updated.
        request: Included source positions, prior answers, and optional list to
            preview as updated instead of newly added.

    Returns:
        Series nodes, genuine overlap questions with both choice effects, the
        issue directory with active blockers, and any cycle rejection.

    Raises:
        HTTPException: 404 for a missing/inactive source list or a foreign
            target list, and 422 for unknown/unresolved source positions or an
            unknown overlap answer.
    """
    source = await get_cbl_source_list_preview(db, list_id=source_list_id, offset=0, limit=1)
    if source is None:
        raise _http_error(
            "cbl_source_not_found",
            f"CBL source list {source_list_id} was not found or is inactive",
            status_code=http_status.HTTP_404_NOT_FOUND,
        )
    report = await reconcile_cbl_source_list(db, user_id=user_id, list_id=source_list_id)
    entries_by_position = {int(entry["cbl_position"]): entry for entry in report.entries}
    selected_positions = sorted(set(request.included_positions))
    unknown = [position for position in selected_positions if position not in entries_by_position]
    if unknown:
        raise _http_error(
            "unknown_source_position",
            f"Source positions are not part of list {source_list_id}: {unknown}",
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    selected = [entries_by_position[position] for position in selected_positions]
    unresolved = [
        int(entry["cbl_position"]) for entry in selected if entry.get("resolved_issue_id") is None
    ]
    if unresolved:
        raise _http_error(
            "unresolved_source_position",
            f"Resolve these source positions before previewing the graph: {unresolved}",
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    threads = await authoring.load_threads(db, user_id)
    issues = await authoring.load_issues(db, user_id)
    owned_lists = await authoring.load_lists(db, user_id)
    list_entries = await authoring.load_entries(db, user_id)
    prerequisites = await authoring.load_requirements(db, user_id)
    excluded = await authoring.load_excluded_issue_ids(db, user_id, issues)
    volume_by_thread = await preview_repository.resolve_thread_volume_keys(
        db, user_id, [thread.id for thread in threads]
    )
    volume_years = await preview_repository.load_volume_years(db, tuple(volume_by_thread.values()))

    issue_meta = {
        issue.id: _IssueMeta(
            issue_id=issue.id,
            thread_id=issue.thread_id,
            issue_number=issue.issue_number,
            position=issue.position,
            status=issue.status,
        )
        for issue in issues
    }
    thread_names = {thread.id: thread.title for thread in threads}
    owned_issue_ids = set(issue_meta)

    selected_issue_ids: list[int] = []
    seen_issue_ids: set[int] = set()
    for entry in selected:
        issue_id = int(entry["resolved_issue_id"])
        if issue_id not in owned_issue_ids:
            raise _http_error(
                "source_position_not_owned",
                f"Source position {entry['cbl_position']} does not resolve to an owned issue",
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if issue_id not in seen_issue_ids:
            seen_issue_ids.add(issue_id)
            selected_issue_ids.append(issue_id)

    target_list_id = request.target_list_id
    target_list = next((row for row in owned_lists if row.id == target_list_id), None)
    if target_list_id is not None and target_list is None:
        raise _http_error(
            "reading_list_not_found",
            f"Reading List {target_list_id} was not found",
            status_code=http_status.HTTP_404_NOT_FOUND,
        )
    proposed_list_id = (
        target_list.id
        if target_list is not None
        else max((row.id for row in owned_lists), default=0) + 1
    )
    proposed_mode = target_list.mode if target_list is not None else "strict"
    proposed_name = target_list.name if target_list is not None else source.name

    entries_by_list: dict[int, list[CustomCBLEntry]] = {}
    for entry in list_entries:
        entries_by_list.setdefault(entry.list_id, []).append(entry)
    target_entries = {entry.issue_id: entry for entry in entries_by_list.get(proposed_list_id, ())}
    proposed_entries = tuple(
        ReadingListEntry(
            issue_id,
            target_entries[issue_id].gate if issue_id in target_entries else "none",
            target_entries[issue_id].skipped if issue_id in target_entries else False,
        )
        for issue_id in selected_issue_ids
    )

    source_names: dict[str, tuple[str, int | None]] = {}
    for entry in selected:
        volume_id = _volume_key(entry.get("series_provider"), entry.get("series_external_id"))
        if volume_id is None:
            continue
        year = entry.get("volume_year")
        if isinstance(year, bool) or not isinstance(year, int):
            publication_year = entry.get("publication_year")
            year = publication_year if isinstance(publication_year, int) else None
        source_names.setdefault(volume_id, (str(entry.get("series_name") or ""), year))

    context = _GraphContext(
        snapshot=ReadingSnapshot(
            user_id=user_id,
            threads=tuple(
                ReadingThread(
                    thread.id,
                    thread.status,
                    thread.title,
                    volume_by_thread.get(thread.id),
                )
                for thread in threads
            ),
            issues=tuple(
                ReadingIssue(issue.id, issue.thread_id, issue.position, issue.status)
                for issue in issues
            ),
            lists=_snapshot_lists(
                owned_lists=owned_lists,
                entries_by_list=entries_by_list,
                proposed_list_id=proposed_list_id,
                proposed_mode=proposed_mode,
                proposed_entries=proposed_entries,
                proposed_name=proposed_name,
                decisions=(),
            ),
            prerequisites=tuple(
                ReadingPrerequisite(
                    row.id,
                    row.source_issue_id,
                    row.target_issue_id,
                    row.origin or "converted",
                    (row.provenance or "",),
                )
                for row in prerequisites
            ),
            excluded_issue_ids=excluded,
        ),
        proposed_list_id=proposed_list_id,
        graph_thread_ids=frozenset(),
        graph_issue_ids=frozenset(),
        issue_meta=issue_meta,
        volume_by_issue={
            issue_id: volume_by_thread.get(meta.thread_id) for issue_id, meta in issue_meta.items()
        },
        series_refs={},
        list_names={row.id: row.name for row in owned_lists} | {proposed_list_id: proposed_name},
        thread_names=thread_names,
    )
    graph_thread_ids = _expand_graph_threads(
        context.snapshot,
        {issue_meta[issue_id].thread_id for issue_id in selected_issue_ids},
        issue_meta,
    )
    graph_issue_ids = frozenset(
        issue_id for issue_id, meta in issue_meta.items() if meta.thread_id in graph_thread_ids
    )
    series_refs: dict[str, ReadingGraphSeriesReference] = {}
    for thread_id in graph_thread_ids:
        volume_id = volume_by_thread.get(thread_id)
        key = volume_id or f"unidentified-thread:{thread_id}"
        series_refs[key] = _series_reference(
            volume_id,
            thread_id,
            thread_names=thread_names,
            source_names=source_names,
            volume_years=volume_years,
        )
    context = _GraphContext(
        snapshot=context.snapshot,
        proposed_list_id=proposed_list_id,
        graph_thread_ids=graph_thread_ids,
        graph_issue_ids=graph_issue_ids,
        issue_meta=issue_meta,
        volume_by_issue=context.volume_by_issue,
        series_refs=series_refs,
        list_names=context.list_names,
        thread_names=thread_names,
    )

    baseline = evaluate(context.snapshot)
    pairs: set[tuple[str, str]] = set()
    blocked_by_pair: dict[tuple[str, str], set[int]] = {}
    for issue_id in selected_issue_ids:
        meta = issue_meta[issue_id]
        state = baseline.get(meta.thread_id)
        continuing_volume = volume_by_thread.get(meta.thread_id)
        if state is None or state.next_issue_id != issue_id or continuing_volume is None:
            continue
        for blocker in state.blockers:
            if blocker.kind != "strict_order" or blocker.list_id != proposed_list_id:
                continue
            for waiting_issue_id in blocker.waiting_on_issue_ids:
                waiting_volume = context.volume_by_issue.get(waiting_issue_id)
                if waiting_volume is None or waiting_volume == continuing_volume:
                    continue
                pair = (continuing_volume, waiting_volume)
                pairs.add(pair)
                blocked_by_pair.setdefault(pair, set()).add(issue_id)

    identified = {pair: _overlap_identity(*pair) for pair in pairs}
    choices_by_identity: dict[str, tuple[tuple[str, str], ReadingGraphChoiceId]] = {}
    for answer in request.overlap_choices:
        pair = next(
            (
                candidate
                for candidate, identity in identified.items()
                if identity == answer.overlap_id
            ),
            None,
        )
        if pair is None:
            raise _http_error(
                "unknown_overlap_choice",
                f"Overlap {answer.overlap_id} is not part of this proposed graph",
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if answer.overlap_id in choices_by_identity:
            raise _http_error(
                "duplicate_overlap_choice",
                f"Overlap {answer.overlap_id} was answered more than once",
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        choices_by_identity[answer.overlap_id] = (pair, answer.choice)
    requested = dict(choices_by_identity.values())

    top_snapshot = _build_snapshot(
        context,
        _decisions(requested),
        owned_lists=owned_lists,
        entries_by_list=entries_by_list,
        proposed_mode=proposed_mode,
        proposed_entries=proposed_entries,
        proposed_name=proposed_name,
    )
    top_eligibility = evaluate(top_snapshot)
    issue_labels = {issue_id: _issue_label(context, issue_id) for issue_id in issue_meta}

    overlaps: list[ReadingGraphOverlap] = []
    for pair in sorted(pairs, key=_pair_sort_key):
        continuing_volume, waiting_volume = pair
        continuing_ref = series_refs[continuing_volume]
        waiting_ref = series_refs[waiting_volume]
        selected_choice = requested.get(pair)
        without_pair = dict(requested)
        without_pair.pop(pair, None)
        protect_decisions = _decisions(without_pair)
        continue_decisions = _decisions({**without_pair, pair: "continue_series"})
        effect_args = {
            "owned_lists": owned_lists,
            "entries_by_list": entries_by_list,
            "proposed_mode": proposed_mode,
            "proposed_entries": proposed_entries,
            "proposed_name": proposed_name,
        }
        protect_effect = _choice_effect(
            context,
            choice="protect_order",
            decisions=protect_decisions,
            continuing=continuing_ref,
            waiting=waiting_ref,
            **effect_args,
        )
        continue_effect = _choice_effect(
            context,
            choice="continue_series",
            decisions=continue_decisions,
            continuing=continuing_ref,
            waiting=waiting_ref,
            **effect_args,
        )
        overlaps.append(
            ReadingGraphOverlap(
                overlap_id=identified[pair],
                continuing_series=continuing_ref,
                waiting_series=waiting_ref,
                question=(
                    f"Should {continuing_ref.series_name} continue while "
                    f"{waiting_ref.series_name} waits?"
                ),
                blocked_issue_ids=sorted(blocked_by_pair.get(pair, ())),
                choices=[continue_effect, protect_effect],
                selected_choice=selected_choice,
            )
        )

    return ReadingGraphPreview(
        source_list_id=source_list_id,
        content_hash=source.content_hash,
        revision_sha=source.revision_sha,
        series=_series_nodes(context, top_eligibility),
        overlaps=overlaps,
        issues=_issue_references(context, top_eligibility),
        rollable_issue_ids=_rollable_ids(context, top_eligibility),
        waiting_issue_ids=_waiting_ids(context, top_eligibility),
        cycle_errors=_cycle_errors(
            top_snapshot,
            list_names=context.list_names,
            thread_names=thread_names,
            issue_labels=issue_labels,
        ),
    )
