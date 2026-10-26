"""Project a reader's canonical graph without globally excluded issues."""

from dataclasses import replace

from app.services.reading_list_evaluator import ReadingSnapshot


def effective_reading_snapshot(snapshot: ReadingSnapshot) -> ReadingSnapshot:
    """Remove excluded issues and their gates for live-order implication tests."""
    excluded = snapshot.excluded_issue_ids
    if not excluded:
        return snapshot
    return replace(
        snapshot,
        issues=tuple(
            issue for issue in snapshot.issues if issue.issue_id not in excluded
        ),
        lists=tuple(
            replace(
                reading_list,
                entries=tuple(
                    entry for entry in reading_list.entries
                    if entry.issue_id not in excluded
                ),
            )
            for reading_list in snapshot.lists
        ),
        prerequisites=tuple(
            edge for edge in snapshot.prerequisites
            if edge.source_issue_id not in excluded
            and edge.target_issue_id not in excluded
        ),
        excluded_issue_ids=frozenset(),
    )
