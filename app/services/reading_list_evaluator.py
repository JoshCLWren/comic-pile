"""Pure Option E eligibility for one complete, reader-owned snapshot.

DTOs contain scalar values only, independent of ORM models and schema rollout.
The loader must supply all referenced issues (including prerequisite sources in
inactive Threads), and resolved collection exclusions. Only active Threads are
returned. Lists in the snapshot are applicable execution lists, not archival
copies. No stored frontier, counter, title or generated edge chooses eligibility.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ReadingIssue:
    """Global issue state and natural series position for this reader."""

    issue_id: int
    thread_id: int
    position: int
    status: str = "unread"


@dataclass(frozen=True, slots=True)
class ReadingThread:
    """Thread identity and activity, independent of cached progress counters."""

    thread_id: int
    status: str = "active"
    name: str = ""


@dataclass(frozen=True, slots=True)
class ReadingListEntry:
    """One curated placement with its list-local skip and positional gate."""

    issue_id: int
    gate: Literal["none", "hold", "after_previous"] = "none"
    skipped: bool = False


@dataclass(frozen=True, slots=True)
class ReadingList:
    """An applicable list whose tuple order is its curated reading order."""

    list_id: int
    mode: Literal["strict", "loose"]
    entries: tuple[ReadingListEntry, ...] = ()
    name: str = ""

    def __post_init__(self) -> None:
        """Detach entries from any mutable input container."""
        object.__setattr__(self, "entries", tuple(self.entries))
        if self.mode not in ("strict", "loose"):
            raise ValueError(f"Unknown list mode: {self.mode}")
        if len({entry.issue_id for entry in self.entries}) != len(self.entries):
            raise ValueError(f"Duplicate issue in list {self.list_id}")
        if any(entry.gate not in ("none", "hold", "after_previous") for entry in self.entries):
            raise ValueError(f"Unknown gate in list {self.list_id}")


@dataclass(frozen=True, slots=True)
class ReadingPrerequisite:
    """Stable source-to-target requirement, independent of list edits."""

    prerequisite_id: int
    source_issue_id: int
    target_issue_id: int
    origin: Literal["reader", "converted"] = "reader"
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Preserve immutable provenance and reject unsupported origins."""
        object.__setattr__(self, "provenance", tuple(self.provenance))
        if self.origin not in ("reader", "converted"):
            raise ValueError(f"Unknown prerequisite origin: {self.origin}")


@dataclass(frozen=True, slots=True)
class ReadingSnapshot:
    """Complete immutable execution inputs belonging to exactly one reader.

    Missing references fail closed rather than silently removing restrictions.
    Excluding a prerequisite source is a stranded prerequisite, which the write
    validator must resolve before constructing a valid execution snapshot.
    """

    user_id: int
    threads: tuple[ReadingThread, ...] = ()
    issues: tuple[ReadingIssue, ...] = ()
    lists: tuple[ReadingList, ...] = ()
    prerequisites: tuple[ReadingPrerequisite, ...] = ()
    excluded_issue_ids: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        """Copy containers and validate snapshot referential completeness."""
        for field in ("threads", "issues", "lists", "prerequisites"):
            object.__setattr__(self, field, tuple(getattr(self, field)))
        object.__setattr__(self, "excluded_issue_ids", frozenset(self.excluded_issue_ids))
        thread_ids = {thread.thread_id for thread in self.threads}
        issue_ids = {issue.issue_id for issue in self.issues}
        identities = (
            (thread_ids, len(self.threads)),
            (issue_ids, len(self.issues)),
            ({reading_list.list_id for reading_list in self.lists}, len(self.lists)),
            ({p.prerequisite_id for p in self.prerequisites}, len(self.prerequisites)),
        )
        if any(len(ids) != count for ids, count in identities):
            raise ValueError("Duplicate snapshot identity")
        if any(issue.thread_id not in thread_ids for issue in self.issues):
            raise ValueError("Issue references a missing Thread")
        referenced = {entry.issue_id for reading_list in self.lists for entry in reading_list.entries}
        referenced.update(p.source_issue_id for p in self.prerequisites)
        referenced.update(p.target_issue_id for p in self.prerequisites)
        referenced.update(self.excluded_issue_ids)
        if missing := referenced - issue_ids:
            raise ValueError(f"Snapshot is missing referenced issues: {sorted(missing)}")
        if any(p.source_issue_id in self.excluded_issue_ids for p in self.prerequisites):
            raise ValueError("Collection exclusion strands an explicit prerequisite")


@dataclass(frozen=True, slots=True)
class Blocker:
    """Concrete unread requirements and their stable list or prerequisite origin."""

    kind: Literal["strict_order", "hold", "after_previous", "prerequisite"]
    list_id: int | None
    waiting_on_issue_ids: tuple[int, ...]
    gate_issue_id: int | None = None
    prerequisite_id: int | None = None
    origin: Literal["reader", "converted"] | None = None
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ThreadEligibility:
    """An active Thread's derived frontier and every applicable restriction."""

    thread_id: int
    next_issue_id: int | None
    blockers: tuple[Blocker, ...] = ()

    @property
    def eligible(self) -> bool:
        """Return whether a concrete unread frontier may be offered."""
        return self.next_issue_id is not None and not self.blockers


def _list_blockers(
    reading_list: ReadingList, unread: frozenset[int], excluded: frozenset[int],
) -> dict[int, list[Blocker]]:
    entries = tuple(
        entry for entry in reading_list.entries
        if not entry.skipped and entry.issue_id not in excluded
    )
    blockers: dict[int, list[Blocker]] = {}
    earlier_unread: list[int] = []
    hold_issue_id: int | None = None
    hold_unread: tuple[int, ...] = ()
    previous: int | None = None
    for entry in entries:
        current: list[Blocker] = []
        if entry.issue_id in unread:
            if reading_list.mode == "strict" and earlier_unread:
                current.append(Blocker("strict_order", reading_list.list_id, tuple(earlier_unread)))
            if hold_unread:
                current.append(Blocker(
                    "hold", reading_list.list_id, hold_unread, gate_issue_id=hold_issue_id,
                ))
            if entry.gate == "hold" and earlier_unread:
                current.append(Blocker(
                    "hold", reading_list.list_id, tuple(earlier_unread),
                    gate_issue_id=entry.issue_id,
                ))
            if entry.gate == "after_previous" and previous in unread:
                current.append(Blocker(
                    "after_previous", reading_list.list_id, (previous,),
                    gate_issue_id=entry.issue_id,
                ))
            if current:
                blockers[entry.issue_id] = current
            earlier_unread.append(entry.issue_id)
        if entry.gate == "hold":
            hold_issue_id = entry.issue_id
            hold_unread = tuple(earlier_unread)
        previous = entry.issue_id
    return blockers


def _blocker_key(blocker: Blocker) -> tuple[str, int, int, int, tuple[int, ...]]:
    return (
        blocker.kind, blocker.list_id if blocker.list_id is not None else -1,
        blocker.gate_issue_id if blocker.gate_issue_id is not None else -1,
        blocker.prerequisite_id if blocker.prerequisite_id is not None else -1,
        blocker.waiting_on_issue_ids,
    )


def evaluate(snapshot: ReadingSnapshot) -> dict[int, ThreadEligibility]:
    """Evaluate active Thread frontiers without I/O, mutation or materialized edges.

    Args:
        snapshot: Complete scalar inputs for one reader. List order is semantic;
            issue, Thread, list and prerequisite container order is not.

    Returns:
        Thread-ID-ordered results, including empty and fully read active Threads.
        Frontier ordering matches #3664: position then stable Issue ID, with only
        status ``read`` considered complete. Blockers sort by kind, list ID,
        gate Issue ID, prerequisite ID, and unread IDs. Within a list blocker,
        unread IDs follow curated list order. Local skips only remove that
        list's restrictions and never suppress a Thread frontier.
    """
    unread = frozenset(issue.issue_id for issue in snapshot.issues if issue.status != "read")
    restrictions: dict[int, list[Blocker]] = {}
    for reading_list in snapshot.lists:
        for issue_id, blockers in _list_blockers(
            reading_list, unread, snapshot.excluded_issue_ids,
        ).items():
            restrictions.setdefault(issue_id, []).extend(blockers)
    for prerequisite in snapshot.prerequisites:
        if prerequisite.source_issue_id in unread:
            restrictions.setdefault(prerequisite.target_issue_id, []).append(Blocker(
                "prerequisite", None, (prerequisite.source_issue_id,),
                prerequisite_id=prerequisite.prerequisite_id,
                origin=prerequisite.origin, provenance=prerequisite.provenance,
            ))
    frontiers: dict[int, ReadingIssue] = {}
    for issue in sorted(snapshot.issues, key=lambda value: (value.position, value.issue_id)):
        if issue.issue_id in unread and issue.issue_id not in snapshot.excluded_issue_ids:
            frontiers.setdefault(issue.thread_id, issue)
    result: dict[int, ThreadEligibility] = {}
    for thread in sorted(snapshot.threads, key=lambda value: value.thread_id):
        if thread.status != "active":
            continue
        frontier = frontiers.get(thread.thread_id)
        issue_id = frontier.issue_id if frontier is not None else None
        result[thread.thread_id] = ThreadEligibility(
            thread.thread_id, issue_id,
            tuple(sorted(restrictions.get(issue_id, ()), key=_blocker_key))
            if issue_id is not None else (),
        )
    return result
