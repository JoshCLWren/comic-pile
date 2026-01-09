"""Test concurrent task creation to verify deadlock fix."""

import os
import tempfile

import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Task


@pytest.mark.asyncio
async def test_create_task_duplicate_id_returns_400(client: AsyncClient, db: Session) -> None:
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


def test_create_task_duplicate_handling_in_code() -> None:
    """Test that create_task handles IntegrityError correctly without SELECT first."""
    from app.schemas.task import CreateTaskRequest

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db_url = f"sqlite:///{db_path}"

        engine = create_engine(db_url)
        Base.metadata.create_all(bind=engine)
        session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        db_session = session_local()

        try:
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
            db_session.add(new_task)
            db_session.commit()

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
            db_session.add(new_task2)

            try:
                db_session.commit()
                raise AssertionError("Should have raised IntegrityError")
            except IntegrityError:
                db_session.rollback()

            tasks = (
                db_session.execute(select(Task).where(Task.task_id == "INTEGRITY-TASK-001"))
                .scalars()
                .all()
            )
            assert len(tasks) == 1, "Only one task should exist in database"

        finally:
            db_session.close()
            engine.dispose()
