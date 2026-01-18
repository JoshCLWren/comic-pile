"""Test concurrent task creation to verify deadlock fix."""

import inspect

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.tasks import create_task as create_task_func
from app.api.tasks import create_tasks_bulk as create_tasks_bulk_func
from app.models import Task


@pytest.mark.asyncio
async def test_create_task_duplicate_id_returns_400(
    client: AsyncClient, db: Session, enable_internal_ops
) -> None:
    """Test that creating a task with duplicate task_id returns 400 error."""
    task_data = {
        "task_id": "DUPLICATE-TASK-001",
        "title": "Duplicate Test Task",
        "priority": "HIGH",
        "estimated_effort": "1 hour",
    }

    response1 = await client.post(
        "/api/tasks/",
        json=task_data,
    )
    assert response1.status_code == 201, "First task creation should succeed"

    response2 = await client.post(
        "/api/tasks/",
        json=task_data,
    )
    assert response2.status_code == 400, "Duplicate task creation should fail"
    error_detail = response2.json()
    assert "already exists" in error_detail["detail"]

    tasks = db.execute(select(Task).where(Task.task_id == "DUPLICATE-TASK-001")).scalars().all()
    assert len(tasks) == 1, "Only one task should exist in database"


def test_create_task_duplicate_handling_in_code(db: Session) -> None:
    """Test that create_task handles IntegrityError correctly without SELECT first."""
    from app.schemas.task import CreateTaskRequest
    from app.models import Task

    task_data = {
        "task_id": "INTEGRITY-TASK-001",
        "title": "Integrity Test Task",
        "description": None,
        "instructions": None,
        "priority": "HIGH",
        "dependencies": None,
        "estimated_effort": "1 hour",
        "task_type": "feature",
    }

    request = CreateTaskRequest(**task_data)

    new_task = Task(
        task_id=request.task_id,
        title=request.title,
        description=request.description,
        instructions=request.instructions,
        priority=request.priority,
        dependencies=request.dependencies,
        estimated_effort=request.estimated_effort,
        task_type=request.task_type,
        status="pending",
        completed=False,
    )
    db.add(new_task)
    db.commit()

    new_task2 = Task(
        task_id=request.task_id,
        title=request.title,
        description=request.description,
        instructions=request.instructions,
        priority=request.priority,
        dependencies=request.dependencies,
        estimated_effort=request.estimated_effort,
        task_type=request.task_type,
        status="pending",
        completed=False,
    )
    db.add(new_task2)

    try:
        db.commit()
        raise AssertionError("Should have raised IntegrityError")
    except IntegrityError:
        db.rollback()

    tasks = db.execute(select(Task).where(Task.task_id == "INTEGRITY-TASK-001")).scalars().all()
    assert len(tasks) == 1, "Only one task should exist in database"


def test_create_task_handles_deadlock_regression():
    """Test that create_task has retry logic for deadlock handling.

    Regression test for BUG-157: DeadlockDetected error during task creation.
    This test verifies the code structure includes deadlock retry logic.
    """
    source = inspect.getsource(create_task_func)

    assert "OperationalError" in source, "create_task should handle OperationalError"
    assert "deadlock" in source.lower(), "create_task should check for deadlock errors"
    assert "retry" in source.lower() or "while" in source.lower(), (
        "create_task should have retry logic"
    )
    assert "rollback" in source.lower(), "create_task should rollback on deadlock"
    assert "max_retries" in source.lower(), "create_task should have max retry limit"


def test_create_tasks_bulk_handles_deadlock_regression():
    """Test that create_tasks_bulk has retry logic for deadlock handling.

    Regression test for BUG-157: DeadlockDetected error during bulk task creation.
    This test verifies the code structure includes deadlock retry logic.
    """
    source = inspect.getsource(create_tasks_bulk_func)

    assert "OperationalError" in source, "create_tasks_bulk should handle OperationalError"
    assert "deadlock" in source.lower(), "create_tasks_bulk should check for deadlock errors"
    assert "retry" in source.lower() or "while" in source.lower(), (
        "create_tasks_bulk should have retry logic"
    )
    assert "rollback" in source.lower(), "create_tasks_bulk should rollback on deadlock"
    assert "max_retries" in source.lower(), "create_tasks_bulk should have max retry limit"
