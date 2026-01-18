"""Tests for task analytics and metrics API."""

import pytest
from datetime import UTC


@pytest.mark.asyncio
async def test_get_analytics_metrics(client, db, enable_internal_ops):
    """Test GET /api/tasks/metrics returns metrics."""
    from app.models import Task as TaskModel

    task1 = TaskModel(
        task_id="TASK-001",
        title="Test Task",
        priority="HIGH",
        status="done",
        estimated_effort="2 hours",
        completed=True,
    )
    task2 = TaskModel(
        task_id="TASK-002",
        title="Test Task 2",
        priority="MEDIUM",
        status="in_progress",
        estimated_effort="1 hour",
        completed=False,
    )
    db.add(task1)
    db.add(task2)
    db.commit()

    response = await client.get("/api/tasks/metrics")

    assert response.status_code == 200
    data = response.json()
    assert "total_tasks" in data
    assert data["total_tasks"] == 2
    assert "tasks_by_status" in data
    assert data["tasks_by_status"]["done"] == 1
    assert data["tasks_by_status"]["in_progress"] == 1
    assert "completion_rate" in data
    assert data["completion_rate"] == 50.0
    assert "tasks_by_priority" in data
    assert "tasks_by_type" in data


@pytest.mark.asyncio
async def test_get_analytics_metrics_empty(client, db, enable_internal_ops):
    """Test GET /api/tasks/metrics with no tasks."""
    response = await client.get("/api/tasks/metrics")

    assert response.status_code == 200
    data = response.json()
    assert data["total_tasks"] == 0
    assert data["completion_rate"] == 0.0
    assert data["average_completion_time_hours"] is None
    assert len(data["recent_completions"]) == 0
    assert len(data["active_agents"]) == 0


@pytest.mark.asyncio
async def test_get_analytics_metrics_completion_time(client, db, enable_internal_ops):
    """Test GET /api/tasks/metrics calculates average completion time."""
    from app.models import Task as TaskModel
    from datetime import datetime

    task1 = TaskModel(
        task_id="TASK-001",
        title="Test Task",
        priority="HIGH",
        status="done",
        estimated_effort="2 hours",
        completed=True,
        created_at=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
    )
    task2 = TaskModel(
        task_id="TASK-002",
        title="Test Task 2",
        priority="MEDIUM",
        status="done",
        estimated_effort="1 hour",
        completed=True,
        created_at=datetime(2025, 1, 2, 10, 0, tzinfo=UTC),
        updated_at=datetime(2025, 1, 2, 11, 0, tzinfo=UTC),
    )
    db.add(task1)
    db.add(task2)
    db.commit()

    response = await client.get("/api/tasks/metrics")

    assert response.status_code == 200
    data = response.json()
    assert data["average_completion_time_hours"] == 1.5
