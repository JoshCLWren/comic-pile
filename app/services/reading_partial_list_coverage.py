"""Read-only audit of unread issues omitted from participating strict lists."""

from app.services.reading_list_evaluator import ReadingSnapshot


def partial_strict_coverage(snapshot: ReadingSnapshot) -> tuple[tuple[int, int], ...]:
    """Identify strict-list omissions; never assume they must be included."""
    lookup = {issue.issue_id: issue.thread_id for issue in snapshot.issues}
    unread = (
        issue for issue in snapshot.issues
        if issue.status != "read" and issue.issue_id not in snapshot.excluded_issue_ids
    )
    missing = []
    for reading_list in snapshot.lists:
        if reading_list.mode != "strict":
            continue
        included = {e.issue_id for e in reading_list.entries if not e.skipped}
        threads = {lookup[issue_id] for issue_id in included}
        for issue in unread:
            if issue.thread_id in threads and issue.issue_id not in included:
                missing.append((reading_list.list_id, issue.issue_id))
    return tuple(sorted(missing))
