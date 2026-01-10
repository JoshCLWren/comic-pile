"""Tests for merge-to-main endpoint."""

import os
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from app.models import Task


@pytest.mark.asyncio
async def test_merge_to_main_not_found(client: AsyncClient) -> None:
    """Test merging a non-existent task returns 404."""
    response = await client.post("/api/tasks/NONEXISTENT/merge-to-main")
    assert response.status_code == 404
    data = response.json()
    assert "Task not found" in data["detail"]


@pytest.mark.asyncio
async def test_merge_to_main_invalid_status(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test merging a task not in in_review status returns 400."""
    response = await client.post("/api/tasks/TASK-101/merge-to-main")
    assert response.status_code == 400
    data = response.json()
    assert "Task must be in_review" in data["detail"]
    assert "pending" in data["detail"]


@pytest.mark.asyncio
async def test_merge_to_main_missing_worktree(client: AsyncClient, db: Session) -> None:
    """Test merging a task with no worktree returns 400."""
    from sqlalchemy import select

    create_response = await client.post(
        "/api/tasks/",
        json={
            "task_id": "MERGE-NO-WORKTREE",
            "title": "Merge Test No Worktree",
            "priority": "HIGH",
            "estimated_effort": "1 hour",
        },
    )
    assert create_response.status_code == 201

    task = db.execute(select(Task).where(Task.task_id == "MERGE-NO-WORKTREE")).scalar_one_or_none()
    if task:
        task.status = "in_review"
        db.commit()

    response = await client.post("/api/tasks/MERGE-NO-WORKTREE/merge-to-main")
    assert response.status_code == 400
    data = response.json()
    assert "No worktree assigned to task" in data["detail"]


@pytest.mark.asyncio
async def test_merge_to_main_worktree_not_found(client: AsyncClient, db: Session) -> None:
    """Test merging a task with non-existent worktree path returns 400."""
    from sqlalchemy import select

    create_response = await client.post(
        "/api/tasks/",
        json={
            "task_id": "MERGE-BAD-PATH",
            "title": "Merge Test Bad Path",
            "priority": "HIGH",
            "estimated_effort": "1 hour",
        },
    )
    assert create_response.status_code == 201

    task = db.execute(select(Task).where(Task.task_id == "MERGE-BAD-PATH")).scalar_one_or_none()
    if task:
        task.status = "in_review"
        task.worktree = "/nonexistent/path"
        db.commit()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch.object(os.path, "exists", return_value=False):
            response = await client.post("/api/tasks/MERGE-BAD-PATH/merge-to-main")
            assert response.status_code == 400
            data = response.json()
            assert "Worktree not found" in data["detail"]


@pytest.mark.asyncio
async def test_merge_to_main_git_fetch_failure(client: AsyncClient, db: Session) -> None:
    """Test merging when git fetch fails returns 500."""
    from sqlalchemy import select

    create_response = await client.post(
        "/api/tasks/",
        json={
            "task_id": "MERGE-FETCH-FAIL",
            "title": "Merge Test Fetch Fail",
            "priority": "HIGH",
            "estimated_effort": "1 hour",
        },
    )
    assert create_response.status_code == 201

    task = db.execute(select(Task).where(Task.task_id == "MERGE-FETCH-FAIL")).scalar_one_or_none()
    if task:
        task.status = "in_review"
        task.worktree = "/tmp/test-worktree"
        db.commit()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Failed to connect to remote"
        )

        with patch.object(os.path, "exists", return_value=True):
            with patch.object(os, "chdir"):
                response = await client.post("/api/tasks/MERGE-FETCH-FAIL/merge-to-main")
                assert response.status_code == 500
                data = response.json()
                assert "Failed to fetch main" in data["detail"]


@pytest.mark.asyncio
async def test_merge_to_main_conflict_appends_status_notes(
    client: AsyncClient, db: Session
) -> None:
    """Test that merge conflicts append to existing status notes."""
    from sqlalchemy import select

    create_response = await client.post(
        "/api/tasks/",
        json={
            "task_id": "MERGE-NOTES-CONFLICT",
            "title": "Merge Test Notes Conflict",
            "priority": "HIGH",
            "estimated_effort": "1 hour",
        },
    )
    assert create_response.status_code == 201

    task = db.execute(
        select(Task).where(Task.task_id == "MERGE-NOTES-CONFLICT")
    ).scalar_one_or_none()
    if task:
        task.status = "in_review"
        task.worktree = "/tmp/test-worktree"
        task.status_notes = "Previous notes before merge"
        db.commit()

    with patch("subprocess.run") as mock_run:

        def run_side_effect(*args, **kwargs):
            if "fetch" in args[0]:
                return MagicMock(returncode=0, stdout="", stderr="")
            elif "merge" in args[0]:
                return MagicMock(
                    returncode=1,
                    stdout="CONFLICT (content): Merge conflict in file.py\n",
                    stderr="",
                )

        mock_run.side_effect = run_side_effect

        with patch.object(os.path, "exists", return_value=True):
            with patch.object(os, "chdir"):
                await client.post("/api/tasks/MERGE-NOTES-CONFLICT/merge-to-main")

                get_response = await client.get("/api/tasks/MERGE-NOTES-CONFLICT")
                task_data = get_response.json()
                assert "Previous notes before merge" in task_data["status_notes"]
                assert "Auto-merge failed" in task_data["status_notes"]
                assert "git merge conflict" in task_data["status_notes"]


@pytest.mark.asyncio
async def test_merge_to_main_absolute_worktree_path(client: AsyncClient, db: Session) -> None:
    """Test that absolute worktree paths are used as-is."""
    from sqlalchemy import select

    create_response = await client.post(
        "/api/tasks/",
        json={
            "task_id": "MERGE-ABS-PATH",
            "title": "Merge Test Absolute Path",
            "priority": "HIGH",
            "estimated_effort": "1 hour",
        },
    )
    assert create_response.status_code == 201

    absolute_path = "/home/josh/code/comic-pile-test"
    task = db.execute(select(Task).where(Task.task_id == "MERGE-ABS-PATH")).scalar_one_or_none()
    if task:
        task.status = "in_review"
        task.worktree = absolute_path
        db.commit()

    with patch("subprocess.run") as mock_run:

        def run_side_effect(*args, **kwargs):
            if "fetch" in args[0]:
                return MagicMock(returncode=0, stdout="", stderr="")
            elif "merge" in args[0]:
                return MagicMock(returncode=0, stdout="Merge successful", stderr="")
            elif "push" in args[0]:
                return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = run_side_effect

        with patch.object(os.path, "exists", return_value=True):
            with patch.object(os, "chdir") as mock_chdir:
                await client.post("/api/tasks/MERGE-ABS-PATH/merge-to-main")
                mock_chdir.assert_called_once_with(absolute_path)


@pytest.mark.asyncio
async def test_merge_to_main_relative_worktree_path(client: AsyncClient, db: Session) -> None:
    """Test that relative worktree paths are resolved correctly."""
    from sqlalchemy import select

    create_response = await client.post(
        "/api/tasks/",
        json={
            "task_id": "MERGE-REL-PATH",
            "title": "Merge Test Relative Path",
            "priority": "HIGH",
            "estimated_effort": "1 hour",
        },
    )
    assert create_response.status_code == 201

    relative_path = "../comic-pile-test"
    task = db.execute(select(Task).where(Task.task_id == "MERGE-REL-PATH")).scalar_one_or_none()
    if task:
        task.status = "in_review"
        task.worktree = relative_path
        db.commit()

    with patch("subprocess.run") as mock_run:

        def run_side_effect(*args, **kwargs):
            if "fetch" in args[0]:
                return MagicMock(returncode=0, stdout="", stderr="")
            elif "merge" in args[0]:
                return MagicMock(returncode=0, stdout="Merge successful", stderr="")
            elif "push" in args[0]:
                return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = run_side_effect

        with patch.object(os.path, "exists", return_value=True):
            with patch.object(os, "chdir") as mock_chdir:
                with patch.object(os, "getcwd", return_value="/home/josh/code/comic-pile"):
                    await client.post("/api/tasks/MERGE-REL-PATH/merge-to-main")
                    expected_path = "/home/josh/code/../comic-pile-test"
                    mock_chdir.assert_called_once_with(expected_path)


@pytest.mark.asyncio
async def test_merge_to_main_conflict_output_truncated(client: AsyncClient, db: Session) -> None:
    """Test that merge conflict output is truncated to 500 characters."""
    from sqlalchemy import select

    create_response = await client.post(
        "/api/tasks/",
        json={
            "task_id": "MERGE-LONG-OUTPUT",
            "title": "Merge Test Long Output",
            "priority": "HIGH",
            "estimated_effort": "1 hour",
        },
    )
    assert create_response.status_code == 201

    task = db.execute(select(Task).where(Task.task_id == "MERGE-LONG-OUTPUT")).scalar_one_or_none()
    if task:
        task.status = "in_review"
        task.worktree = "/tmp/test-worktree"
        db.commit()

    long_output = "CONFLICT (content): Merge conflict in file1.py\n" * 100

    with patch("subprocess.run") as mock_run:

        def run_side_effect(*args, **kwargs):
            if "fetch" in args[0]:
                return MagicMock(returncode=0, stdout="", stderr="")
            elif "merge" in args[0]:
                return MagicMock(returncode=1, stdout=long_output, stderr="")

        mock_run.side_effect = run_side_effect

        with patch.object(os.path, "exists", return_value=True):
            with patch.object(os, "chdir"):
                response = await client.post("/api/tasks/MERGE-LONG-OUTPUT/merge-to-main")
                assert response.status_code == 200
                data = response.json()
                assert data["success"] is False
                assert len(data["output"]) <= 500


@pytest.mark.asyncio
async def test_merge_to_main_changes_directory(client: AsyncClient, db: Session) -> None:
    """Test that merge operation changes to worktree directory."""
    from sqlalchemy import select

    create_response = await client.post(
        "/api/tasks/",
        json={
            "task_id": "MERGE-CHDIR",
            "title": "Merge Test Chdir",
            "priority": "HIGH",
            "estimated_effort": "1 hour",
        },
    )
    assert create_response.status_code == 201

    task = db.execute(select(Task).where(Task.task_id == "MERGE-CHDIR")).scalar_one_or_none()
    if task:
        task.status = "in_review"
        task.worktree = "/tmp/test-worktree"
        db.commit()

    with patch("subprocess.run") as mock_run:

        def run_side_effect(*args, **kwargs):
            if "fetch" in args[0]:
                return MagicMock(returncode=0, stdout="", stderr="")
            elif "merge" in args[0]:
                return MagicMock(returncode=0, stdout="Merge successful", stderr="")
            elif "push" in args[0]:
                return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = run_side_effect

        with patch.object(os.path, "exists", return_value=True):
            with patch.object(os, "chdir") as mock_chdir:
                await client.post("/api/tasks/MERGE-CHDIR/merge-to-main")
                mock_chdir.assert_called_once()


@pytest.mark.asyncio
async def test_merge_to_main_runs_git_commands(client: AsyncClient, db: Session) -> None:
    """Test that merge runs correct git commands in order."""
    from sqlalchemy import select

    create_response = await client.post(
        "/api/tasks/",
        json={
            "task_id": "MERGE-GIT-CMDS",
            "title": "Merge Test Git Commands",
            "priority": "HIGH",
            "estimated_effort": "1 hour",
        },
    )
    assert create_response.status_code == 201

    task = db.execute(select(Task).where(Task.task_id == "MERGE-GIT-CMDS")).scalar_one_or_none()
    if task:
        task.status = "in_review"
        task.worktree = "/tmp/test-worktree"
        db.commit()

    with patch("subprocess.run") as mock_run:

        def run_side_effect(*args, **kwargs):
            if args[0] == ["git", "fetch", "origin", "main"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            elif args[0] == ["git", "merge", "origin/main", "--no-ff"]:
                return MagicMock(returncode=0, stdout="Merge successful", stderr="")
            elif args[0] == ["git", "push", "origin", "HEAD:main"]:
                return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = run_side_effect

        with patch.object(os.path, "exists", return_value=True):
            with patch.object(os, "chdir"):
                await client.post("/api/tasks/MERGE-GIT-CMDS/merge-to-main")
                assert mock_run.call_count == 3
                calls = [call[0][0] for call in mock_run.call_args_list]
                assert calls[0] == ["git", "fetch", "origin", "main"]
                assert calls[1] == ["git", "merge", "origin/main", "--no-ff"]
                assert calls[2] == ["git", "push", "origin", "HEAD:main"]
