"""Tests for retro report API endpoints."""

import pytest
from httpx import AsyncClient

from app.models import Task


@pytest.fixture
def sample_retro_tasks(db) -> list:
    """Create sample tasks for retro report testing."""
    tasks = [
        Task(
            task_id="TASK-101",
            title="Complete Narrative Session Summaries",
            priority="HIGH",
            status="done",
            session_id="SESSION-001",
            assigned_agent="Alice",
            worktree="/home/josh/code/comic-pile-task-101",
            estimated_effort="4 hours",
        ),
        Task(
            task_id="TASK-102",
            title="Add Dice Ladder to API",
            priority="HIGH",
            status="blocked",
            blocked_reason="Waiting on TASK-101",
            blocked_by="dependency",
            session_id="SESSION-001",
            assigned_agent="Bob",
            worktree="/home/josh/code/comic-pile-task-102",
            estimated_effort="3 hours",
        ),
        Task(
            task_id="TASK-103",
            title="Implement Rating System",
            priority="MEDIUM",
            status="in_review",
            session_id="SESSION-001",
            assigned_agent="Charlie",
            worktree="/home/josh/code/comic-pile-task-103",
            estimated_effort="2 hours",
        ),
        Task(
            task_id="TASK-104",
            title="Add Unit Tests",
            priority="MEDIUM",
            status="pending",
            session_id="SESSION-001",
            estimated_effort="3 hours",
        ),
        Task(
            task_id="TASK-201",
            title="Fix Navigation Bug",
            priority="HIGH",
            status="done",
            blocked_reason="Test failure: assertion error in test_navigate_to_comic",
            session_id="SESSION-002",
            assigned_agent="Bob",
            worktree="/home/josh/code/comic-pile-task-201",
            estimated_effort="2 hours",
        ),
        Task(
            task_id="TASK-202",
            title="Optimize Database Queries",
            priority="HIGH",
            status="blocked",
            blocked_reason="Merge conflict with TASK-203 in app/models/session.py",
            session_id="SESSION-002",
            assigned_agent="Charlie",
            worktree="/home/josh/code/comic-pile-task-202",
            estimated_effort="4 hours",
        ),
    ]

    for task in tasks:
        db.add(task)
    db.commit()

    return tasks


async def test_generate_retro_valid_session(client: AsyncClient, sample_retro_tasks) -> None:
    """Test retro generation with valid session ID."""
    response = await client.post("/api/api/retros/generate", json={"session_id": "SESSION-001"})

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "SESSION-001"
    assert data["task_count"] == 4
    assert data["completed_count"] == 1
    assert data["blocked_count"] == 1
    assert data["in_review_count"] == 1
    assert data["failed_tests_count"] == 0
    assert data["merge_conflicts_count"] == 0
    assert len(data["tasks"]) == 4


async def test_generate_retro_nonexistent_session(client: AsyncClient) -> None:
    """Test retro generation with non-existent session ID."""
    response = await client.post("/api/api/retros/generate", json={"session_id": "SESSION-999"})

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "SESSION-999"
    assert data["task_count"] == 0
    assert data["completed_count"] == 0
    assert data["blocked_count"] == 0
    assert data["in_review_count"] == 0
    assert data["failed_tests_count"] == 0
    assert data["merge_conflicts_count"] == 0
    assert data["tasks"] == []


async def test_generate_retro_empty_session(client: AsyncClient, db) -> None:
    """Test retro generation with empty session (no events)."""
    response = await client.post("/api/api/retros/generate", json={"session_id": "SESSION-EMPTY"})

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "SESSION-EMPTY"
    assert data["task_count"] == 0
    assert data["tasks"] == []


async def test_generate_retro_session_with_roll_events(client: AsyncClient, db) -> None:
    """Test retro generation for session containing roll events."""
    task = Task(
        task_id="TASK-105",
        title="Roll Dice Feature",
        priority="HIGH",
        status="done",
        session_id="SESSION-ROLL",
        estimated_effort="2 hours",
    )

    db.add(task)
    db.commit()

    response = await client.post("/api/api/retros/generate", json={"session_id": "SESSION-ROLL"})

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "SESSION-ROLL"
    assert data["task_count"] == 1
    assert data["completed_count"] == 1
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["task_id"] == "TASK-105"
    assert data["tasks"][0]["title"] == "Roll Dice Feature"


async def test_generate_retro_session_with_rate_events(client: AsyncClient, db) -> None:
    """Test retro generation for session containing rate events."""
    task = Task(
        task_id="TASK-106",
        title="Rate Comic Feature",
        priority="HIGH",
        status="done",
        session_id="SESSION-RATE",
        estimated_effort="3 hours",
    )

    db.add(task)
    db.commit()

    response = await client.post("/api/api/retros/generate", json={"session_id": "SESSION-RATE"})

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "SESSION-RATE"
    assert data["task_count"] == 1
    assert data["completed_count"] == 1
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["task_id"] == "TASK-106"


async def test_generate_retro_session_with_mixed_events(client: AsyncClient, db) -> None:
    """Test retro generation for session with various event types."""
    task1 = Task(
        task_id="TASK-107",
        title="Roll Dice Feature",
        priority="HIGH",
        status="done",
        session_id="SESSION-MIXED",
        estimated_effort="2 hours",
    )
    task2 = Task(
        task_id="TASK-108",
        title="Queue Management",
        priority="MEDIUM",
        status="blocked",
        blocked_reason="Missing thread_id in database",
        session_id="SESSION-MIXED",
        estimated_effort="4 hours",
    )

    db.add(task1)
    db.add(task2)
    db.commit()

    response = await client.post("/api/api/retros/generate", json={"session_id": "SESSION-MIXED"})

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "SESSION-MIXED"
    assert data["task_count"] == 2
    assert data["completed_count"] == 1
    assert data["blocked_count"] == 1
    assert data["failed_tests_count"] == 0
    assert data["merge_conflicts_count"] == 0
    assert len(data["tasks"]) == 2


async def test_generate_retro_invalid_session_id(client: AsyncClient) -> None:
    """Test retro generation with invalid session ID (empty string)."""
    response = await client.post("/api/api/retros/generate", json={"session_id": ""})

    assert response.status_code == 422


async def test_generate_retro_status_notes_truncation(client: AsyncClient, db) -> None:
    """Test that retro report includes truncated status notes (last 500 chars)."""
    task_with_long_notes = Task(
        task_id="TASK-109",
        title="Task with Very Long Status Notes",
        priority="LOW",
        status="done",
        session_id="SESSION-001",
        status_notes="A" * 1000,
        estimated_effort="1 hour",
    )
    db.add(task_with_long_notes)
    db.commit()

    response = await client.post("/api/api/retros/generate", json={"session_id": "SESSION-001"})

    assert response.status_code == 200
    data = response.json()
    long_notes_task = [t for t in data["tasks"] if t["task_id"] == "TASK-109"][0]
    assert long_notes_task is not None
    assert long_notes_task["status_notes"] == "A" * 500
    assert len(long_notes_task["status_notes"]) == 500
