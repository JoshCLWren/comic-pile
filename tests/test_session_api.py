"""Tests for session API with issue metadata."""




def _assert_issue_metadata(
    active_thread: dict[str, object],
    *,
    issue_id: int | None,
    issue_number: str | None,
) -> None:
    assert active_thread["issue_id"] == issue_id
    assert active_thread["issue_number"] == issue_number
    assert active_thread["next_issue_id"] == issue_id
    assert active_thread["next_issue_number"] == issue_number








