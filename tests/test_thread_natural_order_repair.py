"""Tests for the reviewed natural-order repair pass (#3483).

The pass reseats ordinary numeric threads that were left messy by CBL
adoption appends. It must not infer dependencies, must leave irregular
threads untouched, and must keep preflight read-only.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from app.services.thread_natural_order_repair import (
    CONFIRMATION_TOKEN,
    NaturalOrderRepairError,
    SNAPSHOT_VERSION,
    parse_repair_snapshot,
    repair_thread_natural_issue_order,
    rollback_thread_natural_issue_order,
)
from scripts.repair_thread_natural_issue_order import (
    _write_json_atomic,
    async_main,
    build_parser,
    main,
)
from tests.conftest import get_or_create_user_async


async def _messy_ultimate_xmen(db: AsyncSession, username: str) -> tuple[Thread, list[Issue]]:
    """Build the 17982 shape: #7–#24, then #2–#6, with #7–#12 read."""
    user = await get_or_create_user_async(db, username)
    thread = Thread(
        title="Ultimate X-Men",
        format="comic",
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=23,
        issues_remaining=17,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    numbers = [str(number) for number in range(7, 25)] + [
        str(number) for number in range(2, 7)
    ]
    issues: list[Issue] = []
    for position, number in enumerate(numbers, start=1):
        status = "read" if number.isdigit() and 7 <= int(number) <= 12 else "unread"
        issue = Issue(
            thread_id=thread.id,
            issue_number=number,
            position=position,
            status=status,
            read_at=datetime.now(UTC) if status == "read" else None,
        )
        db.add(issue)
        issues.append(issue)
    await db.flush()
    next_unread = next(issue for issue in issues if issue.issue_number == "13")
    thread.next_unread_issue_id = next_unread.id
    await db.commit()
    return thread, issues


async def _ordered_numbers(db: AsyncSession, thread_id: int) -> list[str]:
    result = await db.execute(
        select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position)
    )
    return [issue.issue_number for issue in result.scalars().all()]


@pytest.mark.asyncio
async def test_preflight_reports_17982_shape_without_writing(
    async_db: AsyncSession,
) -> None:
    """Read-only preflight plans the reseat and leaves positions untouched."""
    thread, issues = await _messy_ultimate_xmen(async_db, "repair-preflight-uxm")
    thread_id = thread.id
    user_id = thread.user_id
    issue_13_id = next(issue.id for issue in issues if issue.issue_number == "13")

    report = await repair_thread_natural_issue_order(
        async_db, user_id=user_id, thread_id=thread_id, commit=False
    )

    assert report.mode == "preflight"
    assert report.committed is False
    assert report.repaired == 1
    assert report.repairs[0].thread_id == thread_id
    assert report.repairs[0].next_unread_issue_id_before == issue_13_id
    assert [
        item.issue_number
        for item in sorted(
            report.repairs[0].issues, key=lambda item: item.position_after
        )
    ] == [str(number) for number in range(2, 25)]

    persisted = await async_db.get(Thread, thread_id)
    assert persisted is not None
    assert await _ordered_numbers(async_db, thread_id) == [
        str(number) for number in range(7, 25)
    ] + [str(number) for number in range(2, 7)]
    assert persisted.next_unread_issue_id == issue_13_id


@pytest.mark.asyncio
async def test_apply_reseats_17982_and_points_next_unread_at_first_unread(
    async_db: AsyncSession,
) -> None:
    """Apply writes natural positions and derived next-unread without touching reads."""
    thread, issues = await _messy_ultimate_xmen(async_db, "repair-apply-uxm")
    read_at = next(issue for issue in issues if issue.issue_number == "12").read_at

    report = await repair_thread_natural_issue_order(
        async_db, user_id=thread.user_id, thread_id=thread.id, commit=True
    )

    assert report.mode == "apply"
    assert report.committed is True
    assert report.repaired == 1
    await async_db.refresh(thread)
    assert await _ordered_numbers(async_db, thread.id) == [
        str(number) for number in range(2, 25)
    ]
    next_unread = await async_db.get(Issue, thread.next_unread_issue_id)
    assert next_unread is not None
    assert next_unread.issue_number == "2"
    issue_12 = next(
        issue
        for issue in (
            await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
        ).scalars().all()
        if issue.issue_number == "12"
    )
    assert issue_12.status == "read"
    assert issue_12.read_at == read_at


@pytest.mark.asyncio
async def test_rollback_restores_snapshot_positions(async_db: AsyncSession) -> None:
    """Rollback from an apply snapshot restores the previous positions."""
    thread, _issues = await _messy_ultimate_xmen(async_db, "repair-rollback-uxm")
    thread_id = thread.id
    user_id = thread.user_id
    original = await _ordered_numbers(async_db, thread_id)
    original_next = thread.next_unread_issue_id

    applied = await repair_thread_natural_issue_order(
        async_db, user_id=user_id, thread_id=thread_id, commit=True
    )
    assert await _ordered_numbers(async_db, thread_id) != original
    assert applied.to_snapshot()["version"] == SNAPSHOT_VERSION

    rolled = await rollback_thread_natural_issue_order(
        async_db, applied.to_snapshot(), commit=True
    )
    assert rolled.mode == "rollback"
    assert rolled.committed is True
    persisted = await async_db.get(Thread, thread_id)
    assert persisted is not None
    assert await _ordered_numbers(async_db, thread_id) == original
    assert persisted.next_unread_issue_id == original_next


@pytest.mark.asyncio
async def test_rollback_restores_drifted_thread_tracking_state(
    async_db: AsyncSession,
) -> None:
    """Rollback restores every Thread field apply mutates, including drifted counters."""
    thread, issues = await _messy_ultimate_xmen(async_db, "repair-rollback-drift")
    drifted_next = next(issue.id for issue in issues if issue.issue_number == "13")
    thread.total_issues = 99
    thread.issues_remaining = 88
    thread.reading_progress = "completed"
    thread.next_unread_issue_id = drifted_next
    await async_db.commit()
    thread_id = thread.id
    user_id = thread.user_id
    original_order = await _ordered_numbers(async_db, thread_id)

    applied = await repair_thread_natural_issue_order(
        async_db, user_id=user_id, thread_id=thread_id, commit=True
    )
    await async_db.refresh(thread)
    assert thread.total_issues == 23
    assert thread.issues_remaining == 17
    assert thread.reading_progress == "in_progress"
    assert applied.repairs[0].thread_state_before.total_issues == 99
    assert applied.repairs[0].thread_state_before.issues_remaining == 88
    assert applied.repairs[0].thread_state_before.reading_progress == "completed"

    await rollback_thread_natural_issue_order(
        async_db, applied.to_snapshot(), commit=True
    )
    persisted = await async_db.get(Thread, thread_id)
    assert persisted is not None
    assert await _ordered_numbers(async_db, thread_id) == original_order
    assert persisted.total_issues == 99
    assert persisted.issues_remaining == 88
    assert persisted.reading_progress == "completed"
    assert persisted.next_unread_issue_id == drifted_next


@pytest.mark.asyncio
async def test_irregular_thread_is_skipped(async_db: AsyncSession) -> None:
    """Annuals and other irregular numbers are never reseated."""
    user = await get_or_create_user_async(async_db, "repair-irregular")
    thread = Thread(
        title="Annuals",
        format="comic",
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
        issues_remaining=2,
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    async_db.add_all(
        [
            Issue(thread_id=thread.id, issue_number="1", position=1, status="unread"),
            Issue(
                thread_id=thread.id,
                issue_number="Annual 1",
                position=2,
                status="unread",
            ),
        ]
    )
    await async_db.commit()

    report = await repair_thread_natural_issue_order(
        async_db, user_id=user.id, thread_id=thread.id, commit=True
    )
    assert report.repaired == 0
    assert report.skipped_irregular == 1
    assert await _ordered_numbers(async_db, thread.id) == ["1", "Annual 1"]


@pytest.mark.asyncio
async def test_already_natural_thread_is_skipped(async_db: AsyncSession) -> None:
    """A thread already in ordinary numeric order is not rewritten."""
    user = await get_or_create_user_async(async_db, "repair-natural")
    thread = Thread(
        title="Already natural",
        format="comic",
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=3,
        issues_remaining=3,
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    async_db.add_all(
        [
            Issue(thread_id=thread.id, issue_number=str(number), position=number)
            for number in range(1, 4)
        ]
    )
    await async_db.commit()

    report = await repair_thread_natural_issue_order(
        async_db, user_id=user.id, thread_id=thread.id, commit=True
    )
    assert report.repaired == 0
    assert report.skipped_already_natural == 1


@pytest.mark.asyncio
async def test_apply_reseats_17977_usm_appended_early_issues(
    async_db: AsyncSession,
) -> None:
    """Ultimate Spider-Man 17977 shape: #1–#2 after later issues become first."""
    user = await get_or_create_user_async(async_db, "repair-apply-usm")
    thread = Thread(
        title="Ultimate Spider-Man",
        format="comic",
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=24,
        issues_remaining=21,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    numbers = [str(number) for number in range(3, 25)] + ["1", "2"]
    issues: list[Issue] = []
    for position, number in enumerate(numbers, start=1):
        status = "read" if number in {"3", "4", "5"} else "unread"
        issue = Issue(
            thread_id=thread.id,
            issue_number=number,
            position=position,
            status=status,
            read_at=datetime.now(UTC) if status == "read" else None,
        )
        async_db.add(issue)
        issues.append(issue)
    await async_db.flush()
    thread.next_unread_issue_id = next(
        issue.id for issue in issues if issue.issue_number == "6"
    )
    await async_db.commit()

    report = await repair_thread_natural_issue_order(
        async_db, user_id=user.id, thread_id=thread.id, commit=True
    )
    assert report.repaired == 1
    await async_db.refresh(thread)
    assert await _ordered_numbers(async_db, thread.id) == [
        str(number) for number in range(1, 25)
    ]
    next_unread = await async_db.get(Issue, thread.next_unread_issue_id)
    assert next_unread is not None
    assert next_unread.issue_number == "1"


def test_cli_requires_subcommand_and_apply_confirmation() -> None:
    """Apply is never the default command and refuses a missing confirm token."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    args = parser.parse_args(
        ["preflight", "--output", "/tmp/natural-order-preflight.json"]
    )
    assert args.command == "preflight"
    assert main(["apply", "--output", "/tmp/natural-order-apply.json"]) == 2
    assert CONFIRMATION_TOKEN == "NATURAL-ISSUE-ORDER-REPAIR"


def test_rollback_snapshot_rejects_bad_version() -> None:
    """Rollback fails closed on an unsupported snapshot."""
    with pytest.raises(NaturalOrderRepairError, match="unsupported"):
        parse_repair_snapshot({"version": 1, "repairs": []})


@pytest.mark.asyncio
async def test_apply_cli_writes_snapshot_before_commit(tmp_path: Path) -> None:
    """Apply publishes the rollback snapshot before commit; write failure rolls back."""
    call_order: list[str] = []
    output = tmp_path / "natural-order-apply.json"

    class _FakeReport:
        mode = "apply"
        scanned = 1
        skipped_irregular = 0
        skipped_already_natural = 0
        repaired = 1
        committed = False
        repairs: tuple[object, ...] = ()

        def to_snapshot(self) -> dict[str, object]:
            return {"version": SNAPSHOT_VERSION, "repairs": []}

    class _FakeSession:
        async def commit(self) -> None:
            call_order.append("commit")

        async def rollback(self) -> None:
            call_order.append("rollback")

        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *_exc: object) -> bool:
            return False

    async def _fake_repair(*_args: object, **kwargs: object) -> _FakeReport:
        call_order.append("repair")
        assert kwargs.get("apply_changes") is True
        assert kwargs.get("commit") is False
        return _FakeReport()

    def _failing_write(path: Path, payload: dict[str, object]) -> None:
        call_order.append("write")
        assert path == output
        assert payload.get("committed") is True
        raise OSError("disk full")

    with (
        patch(
            "scripts.repair_thread_natural_issue_order.AsyncSessionLocal",
            return_value=_FakeSession(),
        ),
        patch(
            "scripts.repair_thread_natural_issue_order.repair_thread_natural_issue_order",
            side_effect=_fake_repair,
        ),
        patch(
            "scripts.repair_thread_natural_issue_order._write_json_atomic",
            side_effect=_failing_write,
        ),
    ):
        with pytest.raises(OSError, match="disk full"):
            await async_main(
                [
                    "apply",
                    "--confirm",
                    CONFIRMATION_TOKEN,
                    "--output",
                    str(output),
                ]
            )

    assert call_order == ["repair", "write", "rollback"]
    assert not output.exists()


@pytest.mark.asyncio
async def test_apply_cli_commits_only_after_snapshot_write(tmp_path: Path) -> None:
    """Successful apply writes the durable snapshot, then commits."""
    call_order: list[str] = []
    output = tmp_path / "natural-order-apply.json"

    class _FakeReport:
        mode = "apply"
        scanned = 1
        skipped_irregular = 0
        skipped_already_natural = 0
        repaired = 1
        committed = False
        repairs: tuple[object, ...] = ()

        def to_snapshot(self) -> dict[str, object]:
            return {"version": SNAPSHOT_VERSION, "repairs": []}

    class _FakeSession:
        async def commit(self) -> None:
            call_order.append("commit")

        async def rollback(self) -> None:
            call_order.append("rollback")

        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *_exc: object) -> bool:
            return False

    async def _fake_repair(*_args: object, **kwargs: object) -> _FakeReport:
        call_order.append("repair")
        assert kwargs.get("apply_changes") is True
        assert kwargs.get("commit") is False
        return _FakeReport()

    def _ok_write(path: Path, payload: dict[str, object]) -> None:
        call_order.append("write")
        path.write_text('{"version": 2, "repairs": []}\n', encoding="utf-8")

    with (
        patch(
            "scripts.repair_thread_natural_issue_order.AsyncSessionLocal",
            return_value=_FakeSession(),
        ),
        patch(
            "scripts.repair_thread_natural_issue_order.repair_thread_natural_issue_order",
            side_effect=_fake_repair,
        ),
        patch(
            "scripts.repair_thread_natural_issue_order._write_json_atomic",
            side_effect=_ok_write,
        ),
    ):
        assert (
            await async_main(
                [
                    "apply",
                    "--confirm",
                    CONFIRMATION_TOKEN,
                    "--output",
                    str(output),
                ]
            )
            == 0
        )

    assert call_order == ["repair", "write", "commit"]
    assert output.exists()


def test_write_json_atomic_replaces_destination(tmp_path: Path) -> None:
    """Atomic snapshot publish leaves a complete JSON object at the destination."""
    path = tmp_path / "snapshot.json"
    _write_json_atomic(path, {"version": SNAPSHOT_VERSION, "ok": True})
    assert path.read_text(encoding="utf-8").startswith("{\n")
    assert '"ok": true' in path.read_text(encoding="utf-8")
