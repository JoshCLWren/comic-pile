"""Tests for task API endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_tasks(client: AsyncClient) -> None:
    """Test listing all tasks."""
    response = await client.get("/api/tasks/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_initialize_tasks(client: AsyncClient) -> None:
    """Test initializing all tasks."""
    response = await client.post("/api/tasks/initialize")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "tasks_created" in data
    assert "tasks_updated" in data
    assert "tasks" in data
    assert len(data["tasks"]) == 12
    assert data["tasks_created"] == 12
    assert data["tasks_updated"] == 0


@pytest.mark.asyncio
async def test_initialize_tasks_idempotent(client: AsyncClient) -> None:
    """Test that initializing tasks is idempotent."""
    await client.post("/api/tasks/initialize")

    response = await client.post("/api/tasks/initialize")
    assert response.status_code == 200
    data = response.json()
    assert data["tasks_created"] == 0
    assert data["tasks_updated"] == 12


@pytest.mark.asyncio
async def test_get_task(client: AsyncClient) -> None:
    """Test getting a single task."""
    await client.post("/api/tasks/initialize")

    response = await client.get("/api/tasks/TASK-101")
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "TASK-101"
    assert data["title"] == "Complete Narrative Session Summaries"
    assert data["priority"] == "HIGH"
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_get_task_not_found(client: AsyncClient) -> None:
    """Test getting a non-existent task."""
    response = await client.get("/api/tasks/TASK-999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_claim_task(client: AsyncClient) -> None:
    """Test claiming a task."""
    await client.post("/api/tasks/initialize")

    response = await client.post(
        "/api/tasks/TASK-101/claim",
        json={"agent_name": "agent-1", "worktree": "comic-pile-task-101"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "in_progress"
    assert data["assigned_agent"] == "agent-1"
    assert data["worktree"] == "comic-pile-task-101"
    assert "Claimed by agent-1" in data["status_notes"]


@pytest.mark.asyncio
async def test_claim_task_not_found(client: AsyncClient) -> None:
    """Test claiming a non-existent task."""
    response = await client.post(
        "/api/tasks/TASK-999/claim",
        json={"agent_name": "agent-1", "worktree": "comic-pile-task-101"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_notes(client: AsyncClient) -> None:
    """Test updating task status notes."""
    await client.post("/api/tasks/initialize")

    response = await client.post(
        "/api/tasks/TASK-101/update-notes",
        json={"notes": "Started working on narrative summary"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "Started working on narrative summary" in data["status_notes"]


@pytest.mark.asyncio
async def test_update_notes_appends(client: AsyncClient) -> None:
    """Test that updating notes appends to existing notes."""
    await client.post("/api/tasks/initialize")

    await client.post(
        "/api/tasks/TASK-101/update-notes",
        json={"notes": "First note"},
    )

    response = await client.post(
        "/api/tasks/TASK-101/update-notes",
        json={"notes": "Second note"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "First note" in data["status_notes"]
    assert "Second note" in data["status_notes"]


@pytest.mark.asyncio
async def test_update_notes_not_found(client: AsyncClient) -> None:
    """Test updating notes for a non-existent task."""
    response = await client.post(
        "/api/tasks/TASK-999/update-notes",
        json={"notes": "Test note"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_set_status(client: AsyncClient) -> None:
    """Test setting task status."""
    await client.post("/api/tasks/initialize")

    response = await client.post(
        "/api/tasks/TASK-101/set-status",
        json={"status": "in_progress"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "in_progress"


@pytest.mark.asyncio
async def test_set_status_to_done(client: AsyncClient) -> None:
    """Test setting task status to done marks completed."""
    await client.post("/api/tasks/initialize")

    response = await client.post(
        "/api/tasks/TASK-101/set-status",
        json={"status": "done"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "done"
    assert data["completed"] is True


@pytest.mark.asyncio
async def test_set_status_invalid(client: AsyncClient) -> None:
    """Test setting invalid task status."""
    await client.post("/api/tasks/initialize")

    response = await client.post(
        "/api/tasks/TASK-101/set-status",
        json={"status": "invalid_status"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_set_status_not_found(client: AsyncClient) -> None:
    """Test setting status for a non-existent task."""
    response = await client.post(
        "/api/tasks/TASK-999/set-status",
        json={"status": "in_progress"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_tasks_by_status(client: AsyncClient) -> None:
    """Test filtering tasks by status."""
    await client.post("/api/tasks/initialize")

    response = await client.get("/api/tasks/by-status/pending")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0


@pytest.mark.asyncio
async def test_get_tasks_by_agent(client: AsyncClient) -> None:
    """Test getting tasks assigned to a specific agent."""
    await client.post("/api/tasks/initialize")

    await client.post(
        "/api/tasks/TASK-101/claim",
        json={"agent_name": "agent-1", "worktree": "comic-pile-task-101"},
    )

    response = await client.get("/api/tasks/by-agent/agent-1")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["task_id"] == "TASK-101"
    assert data[0]["assigned_agent"] == "agent-1"


@pytest.mark.asyncio
async def test_claim_task_conflict(client: AsyncClient) -> None:
    """Test atomic claim with conflict response."""
    await client.post("/api/tasks/initialize")

    response = await client.post(
        "/api/tasks/TASK-101/claim",
        json={"agent_name": "agent-1", "worktree": "comic-pile-task-101"},
    )
    assert response.status_code == 200

    response = await client.post(
        "/api/tasks/TASK-101/claim",
        json={"agent_name": "agent-2", "worktree": "comic-pile-task-102"},
    )
    assert response.status_code == 409
    data = response.json()
    assert "detail" in data
    assert data["detail"]["error"] == "Task already claimed"
    assert data["detail"]["current_assignee"] == "agent-1"
    assert data["detail"]["task_id"] == "TASK-101"


@pytest.mark.asyncio
async def test_heartbeat_endpoint(client: AsyncClient) -> None:
    """Test heartbeat endpoint by owner and non-owner."""
    await client.post("/api/tasks/initialize")

    await client.post(
        "/api/tasks/TASK-101/claim",
        json={"agent_name": "agent-1", "worktree": "comic-pile-task-101"},
    )

    response = await client.post(
        "/api/tasks/TASK-101/heartbeat",
        json={"agent_name": "agent-1"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["last_heartbeat"] is not None

    response = await client.post(
        "/api/tasks/TASK-101/heartbeat",
        json={"agent_name": "agent-2"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_unclaim_endpoint(client: AsyncClient) -> None:
    """Test unclaim endpoint by owner and non-owner."""
    await client.post("/api/tasks/initialize")

    await client.post(
        "/api/tasks/TASK-101/claim",
        json={"agent_name": "agent-1", "worktree": "comic-pile-task-101"},
    )

    response = await client.post(
        "/api/tasks/TASK-101/unclaim",
        json={"agent_name": "agent-1"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["assigned_agent"] is None
    assert data["worktree"] is None
    assert "Unclaimed by agent-1" in data["status_notes"]

    response = await client.post(
        "/api/tasks/TASK-102/unclaim",
        json={"agent_name": "agent-2"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_blocked_fields(client: AsyncClient) -> None:
    """Test setting blocked_reason and blocked_by."""
    await client.post("/api/tasks/initialize")

    response = await client.post(
        "/api/tasks/TASK-101/set-status",
        json={
            "status": "blocked",
            "blocked_reason": "Waiting for dependency",
            "blocked_by": "TASK-102",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "blocked"
    assert data["blocked_reason"] == "Waiting for dependency"
    assert data["blocked_by"] == "TASK-102"


@pytest.mark.asyncio
async def test_ready_tasks(client: AsyncClient) -> None:
    """Test ready tasks filtering with various dependency states."""
    await client.post("/api/tasks/initialize")

    response = await client.post(
        "/api/tasks/TASK-101/set-status",
        json={"status": "blocked", "blocked_reason": "Test block"},
    )
    assert response.status_code == 200

    response = await client.get("/api/tasks/ready")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

    task_ids = [task["task_id"] for task in data]
    assert "TASK-101" not in task_ids

    response = await client.post(
        "/api/tasks/TASK-101/set-status",
        json={"status": "pending"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_coordinator_data(client: AsyncClient) -> None:
    """Test coordinator data endpoint."""
    await client.post("/api/tasks/initialize")

    await client.post(
        "/api/tasks/TASK-101/claim",
        json={"agent_name": "agent-1", "worktree": "comic-pile-task-101"},
    )

    await client.post("/api/tasks/TASK-102/set-status", json={"status": "done"})

    response = await client.get("/api/tasks/coordinator-data")
    assert response.status_code == 200
    data = response.json()
    assert "pending" in data
    assert "in_progress" in data
    assert "blocked" in data
    assert "in_review" in data
    assert "done" in data
    assert len(data["in_progress"]) == 1
    assert data["in_progress"][0]["task_id"] == "TASK-101"
    assert len(data["done"]) == 1
    assert data["done"][0]["task_id"] == "TASK-102"


@pytest.mark.asyncio
async def test_unclaim_in_review_preserves_status(client: AsyncClient) -> None:
    """Test that in_review tasks stay in_review when unclaimed."""
    # Create a task
    create_response = await client.post(
        "/api/tasks/",
        json={
            "task_id": "TEST-1",
            "title": "Test Task",
            "priority": "MEDIUM",
            "description": "Test description",
            "instructions": "Test instructions",
            "estimated_effort": "1 hour",
        },
    )
    assert create_response.status_code == 201
    task = create_response.json()
    assert task["status"] == "pending"

    # Claim the task
    claim_response = await client.post(
        "/api/tasks/TEST-1/claim",
        json={"agent_name": "agent-1", "worktree": "test-worktree"},
    )
    assert claim_response.status_code == 200
    task = claim_response.json()
    assert task["status"] == "in_progress"
    assert task["assigned_agent"] == "agent-1"

    # Set to in_review
    status_response = await client.post(
        "/api/tasks/TEST-1/set-status",
        json={"status": "in_review", "agent_name": "agent-1"},
    )
    assert status_response.status_code == 200
    task = status_response.json()
    assert task["status"] == "in_review"

    # Unclaim the task
    unclaim_response = await client.post(
        "/api/tasks/TEST-1/unclaim",
        json={"agent_name": "agent-1"},
    )
    assert unclaim_response.status_code == 200
    task = unclaim_response.json()

    # Verify status is still in_review
    assert task["status"] == "in_review"
    assert task["assigned_agent"] is None
    assert task["worktree"] is None
    assert "Unclaimed by agent-1" in task["status_notes"]


@pytest.mark.asyncio
async def test_unclaim_in_progress_resets_to_pending(client: AsyncClient) -> None:
    """Test that in_progress tasks are reset to pending when unclaimed."""
    # Create a task
    create_response = await client.post(
        "/api/tasks/",
        json={
            "task_id": "TEST-2",
            "title": "Test Task 2",
            "priority": "MEDIUM",
            "description": "Test description",
            "instructions": "Test instructions",
            "estimated_effort": "1 hour",
        },
    )
    assert create_response.status_code == 201
    task = create_response.json()
    assert task["status"] == "pending"

    # Claim the task
    claim_response = await client.post(
        "/api/tasks/TEST-2/claim",
        json={"agent_name": "agent-1", "worktree": "test-worktree"},
    )
    assert claim_response.status_code == 200
    task = claim_response.json()
    assert task["status"] == "in_progress"
    assert task["assigned_agent"] == "agent-1"

    # Unclaim the task (still in_progress)
    unclaim_response = await client.post(
        "/api/tasks/TEST-2/unclaim",
        json={"agent_name": "agent-1"},
    )
    assert unclaim_response.status_code == 200
    task = unclaim_response.json()

    # Verify status is reset to pending
    assert task["status"] == "pending"
    assert task["assigned_agent"] is None
    assert task["worktree"] is None
    assert "Unclaimed by agent-1" in task["status_notes"]
