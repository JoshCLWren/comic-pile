"""Tests for task API endpoints."""

import pytest
from httpx import AsyncClient

from app.models import Task


@pytest.mark.asyncio
async def test_list_tasks(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test listing all tasks."""
    response = await client.get("/api/tasks/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_task(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test getting a single task."""
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
async def test_claim_task(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test claiming a task."""
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
async def test_update_notes(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test updating task status notes."""
    response = await client.post(
        "/api/tasks/TASK-101/update-notes",
        json={"notes": "Started working on narrative summary"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "Started working on narrative summary" in data["status_notes"]


@pytest.mark.asyncio
async def test_update_notes_appends(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test that updating notes appends to existing notes."""
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
async def test_set_status(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test setting task status."""
    response = await client.post(
        "/api/tasks/TASK-101/set-status",
        json={"status": "in_progress"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "in_progress"


@pytest.mark.asyncio
async def test_set_status_to_done(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test setting task status to done marks completed."""
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
async def test_get_tasks_by_status(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test filtering tasks by status."""
    response = await client.get("/api/tasks/by-status/pending")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0


@pytest.mark.asyncio
async def test_get_tasks_by_agent(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test getting tasks assigned to a specific agent."""
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
async def test_claim_task_conflict(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test atomic claim with conflict response."""
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
async def test_claim_with_valid_worker_type(client: AsyncClient) -> None:
    """Test claiming a task with valid worker_type."""
    import os

    os.environ["SKIP_WORKTREE_CHECK"] = "true"
    try:
        await client.post(
            "/api/tasks/",
            json={
                "task_id": "TEST-TYPE-1",
                "title": "Test Type Task",
                "priority": "HIGH",
                "task_type": "test_failure",
                "estimated_effort": "1 hour",
            },
        )

        response = await client.post(
            "/api/tasks/TEST-TYPE-1/claim",
            json={
                "agent_name": "test-fixer",
                "worktree": "test-worktree",
                "worker_type": "test-fixer",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "in_progress"
        assert data["assigned_agent"] == "test-fixer"
    finally:
        os.environ.pop("SKIP_WORKTREE_CHECK", None)


@pytest.mark.asyncio
async def test_claim_with_invalid_worker_type(client: AsyncClient) -> None:
    """Test that wrong worker_type cannot claim incompatible task_type."""
    import os

    os.environ["SKIP_WORKTREE_CHECK"] = "true"
    try:
        await client.post(
            "/api/tasks/",
            json={
                "task_id": "TEST-TYPE-2",
                "title": "Test Type Task",
                "priority": "HIGH",
                "task_type": "feature",
                "estimated_effort": "1 hour",
            },
        )

        response = await client.post(
            "/api/tasks/TEST-TYPE-2/claim",
            json={
                "agent_name": "test-fixer",
                "worktree": "test-worktree",
                "worker_type": "test-fixer",
            },
        )
        assert response.status_code == 403
        data = response.json()
        assert "test-fixer cannot claim feature tasks" in data["detail"]
    finally:
        os.environ.pop("SKIP_WORKTREE_CHECK", None)


@pytest.mark.asyncio
async def test_claim_without_worker_type(client: AsyncClient) -> None:
    """Test claiming a task without specifying worker_type (no filtering)."""
    import os

    os.environ["SKIP_WORKTREE_CHECK"] = "true"
    try:
        await client.post(
            "/api/tasks/",
            json={
                "task_id": "TEST-TYPE-3",
                "title": "Test Type Task",
                "priority": "HIGH",
                "task_type": "feature",
                "estimated_effort": "1 hour",
            },
        )

        response = await client.post(
            "/api/tasks/TEST-TYPE-3/claim",
            json={
                "agent_name": "test-fixer",
                "worktree": "test-worktree",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "in_progress"
        assert data["assigned_agent"] == "test-fixer"
    finally:
        os.environ.pop("SKIP_WORKTREE_CHECK", None)


@pytest.mark.asyncio
async def test_patch_task_type(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test PATCH endpoint to update task_type."""
    response = await client.patch(
        "/api/tasks/TASK-101",
        json={"task_type": "bug_fix"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["task_type"] == "bug_fix"
    assert data["task_id"] == "TASK-101"


@pytest.mark.asyncio
async def test_patch_invalid_task_type(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test PATCH endpoint with invalid task_type returns 400."""
    response = await client.patch(
        "/api/tasks/TASK-101",
        json={"task_type": "invalid_type"},
    )
    assert response.status_code == 400
    data = response.json()
    assert "Invalid task_type" in data["detail"]


@pytest.mark.asyncio
async def test_heartbeat_endpoint(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test heartbeat endpoint by owner and non-owner."""
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
async def test_unclaim_endpoint(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test unclaim endpoint by owner and non-owner."""
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
async def test_blocked_fields(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test setting blocked_reason and blocked_by."""
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
async def test_ready_tasks(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test ready tasks filtering with various dependency states."""
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
async def test_coordinator_data(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test coordinator data endpoint."""
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
    """Test that unclaiming in_review tasks preserves their status and worktree."""
    # Create a task
    create_response = await client.post(
        "/api/tasks/",
        json={
            "task_id": "TEST-1",
            "title": "Test Task 1",
            "priority": "HIGH",
            "instructions": "Test instructions",
            "estimated_effort": "1 hour",
        },
    )
    assert create_response.status_code == 201
    task = create_response.json()
    assert task["status"] == "pending"

    # Claim task with SKIP_WORKTREE_CHECK to bypass worktree validation in tests
    import os

    original_skip = os.environ.get("SKIP_WORKTREE_CHECK")
    os.environ["SKIP_WORKTREE_CHECK"] = "true"

    try:
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

        # Unclaim task
        unclaim_response = await client.post(
            "/api/tasks/TEST-1/unclaim",
            json={"agent_name": "agent-1"},
        )
        assert unclaim_response.status_code == 200
        task = unclaim_response.json()

        # Verify status is still in_review and worktree is preserved
        assert task["status"] == "in_review"
        assert task["assigned_agent"] is None
        assert task["worktree"] == "test-worktree"
        assert "Unclaimed by agent-1" in task["status_notes"]
    finally:
        if original_skip is None:
            os.environ.pop("SKIP_WORKTREE_CHECK", None)
        else:
            os.environ["SKIP_WORKTREE_CHECK"] = original_skip


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


@pytest.mark.asyncio
async def test_patch_task_title(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test PATCH endpoint to update task title."""
    response = await client.patch(
        "/api/tasks/TASK-101",
        json={"title": "Updated Task Title"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated Task Title"
    assert data["task_id"] == "TASK-101"


@pytest.mark.asyncio
async def test_patch_task_priority(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test PATCH endpoint to update task priority."""
    response = await client.patch(
        "/api/tasks/TASK-101",
        json={"priority": "LOW"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["priority"] == "LOW"
    assert data["task_id"] == "TASK-101"


@pytest.mark.asyncio
async def test_patch_task_invalid_priority(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test PATCH endpoint with invalid priority returns 422."""
    response = await client.patch(
        "/api/tasks/TASK-101",
        json={"priority": "INVALID"},
    )
    assert response.status_code == 422
    data = response.json()
    assert "errors" in data
    assert any("priority" in error["field"] for error in data["errors"])


@pytest.mark.asyncio
async def test_patch_task_multiple_fields(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test PATCH endpoint updating multiple fields at once."""
    response = await client.patch(
        "/api/tasks/TASK-101",
        json={
            "title": "Multi-field Update",
            "description": "Updated description",
            "priority": "MEDIUM",
            "estimated_effort": "5 hours",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Multi-field Update"
    assert data["description"] == "Updated description"
    assert data["priority"] == "MEDIUM"
    assert data["estimated_effort"] == "5 hours"


@pytest.mark.asyncio
async def test_patch_task_not_found(client: AsyncClient) -> None:
    """Test PATCH endpoint for non-existent task returns 404."""
    response = await client.patch(
        "/api/tasks/TASK-999",
        json={"title": "Non-existent"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_patch_task_empty_body(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test PATCH endpoint with empty body returns task unchanged."""
    response = await client.patch(
        "/api/tasks/TASK-101",
        json={},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "TASK-101"


@pytest.mark.asyncio
async def test_validation_error_detailed_response(client: AsyncClient) -> None:
    """Test that 422 validation errors return detailed field-specific errors."""
    response = await client.post(
        "/api/tasks/TASK-999/claim",
        json={"agent_name": "", "worktree": "test"},
    )
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data
    assert "Validation failed" in data["detail"]
    assert "errors" in data
    assert any("agent_name" in error["field"] for error in data["errors"])


@pytest.mark.asyncio
async def test_patch_task_with_dependencies(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test PATCH endpoint updating dependencies field."""
    response = await client.patch(
        "/api/tasks/TASK-101",
        json={"dependencies": "TASK-102,TASK-103"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["dependencies"] == "TASK-102,TASK-103"


@pytest.mark.asyncio
async def test_delete_task(client: AsyncClient) -> None:
    """Test deleting a task."""
    # Create a task
    create_response = await client.post(
        "/api/tasks/",
        json={
            "task_id": "TEST-DELETE-1",
            "title": "Task to Delete",
            "priority": "MEDIUM",
            "description": "This task will be deleted",
            "instructions": "Test instructions",
            "estimated_effort": "1 hour",
        },
    )
    assert create_response.status_code == 201

    # Verify task exists
    get_response = await client.get("/api/tasks/TEST-DELETE-1")
    assert get_response.status_code == 200

    # Delete task
    delete_response = await client.delete("/api/tasks/TEST-DELETE-1")
    assert delete_response.status_code == 204

    # Verify task no longer exists
    verify_response = await client.get("/api/tasks/TEST-DELETE-1")
    assert verify_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_task_not_found(client: AsyncClient) -> None:
    """Test deleting a non-existent task."""
    response = await client.delete("/api/tasks/TASK-NONEXISTENT")
    assert response.status_code == 404
    data = response.json()
    assert "TASK-NONEXISTENT not found" in data["detail"]


@pytest.mark.asyncio
async def test_delete_claimed_task(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test deleting a claimed task."""
    # Claim a task
    await client.post(
        "/api/tasks/TASK-101/claim",
        json={"agent_name": "agent-1", "worktree": "comic-pile-task-101"},
    )

    # Delete claimed task
    delete_response = await client.delete("/api/tasks/TASK-101")
    assert delete_response.status_code == 204

    # Verify task no longer exists
    verify_response = await client.get("/api/tasks/TASK-101")
    assert verify_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_task_with_dependencies(client: AsyncClient) -> None:
    """Test that deleting a task with dependencies is rejected."""
    # Create two tasks, one dependent on the other
    await client.post(
        "/api/tasks/",
        json={
            "task_id": "TEST-DEP-1",
            "title": "Task 1",
            "priority": "HIGH",
            "instructions": "Test instructions",
            "estimated_effort": "1 hour",
        },
    )
    await client.post(
        "/api/tasks/",
        json={
            "task_id": "TEST-DEP-2",
            "title": "Task 2 depends on 1",
            "priority": "HIGH",
            "dependencies": "TEST-DEP-1",
            "instructions": "Test instructions",
            "estimated_effort": "1 hour",
        },
    )

    # Try to delete task that has dependencies
    delete_response = await client.delete("/api/tasks/TEST-DEP-1")
    assert delete_response.status_code == 400
    data = delete_response.json()
    assert "Cannot delete task with dependencies" in data["detail"]
    assert "TEST-DEP-2" in data["detail"]


@pytest.mark.asyncio
async def test_delete_task_with_dependencies_admin_override(
    client: AsyncClient,
) -> None:
    """Test that admin override allows deletion of tasks with dependencies."""
    # Create two tasks, one dependent on the other
    await client.post(
        "/api/tasks/",
        json={
            "task_id": "TEST-DEP-OVERRIDE-1",
            "title": "Task 1",
            "priority": "HIGH",
            "instructions": "Test instructions",
            "estimated_effort": "1 hour",
        },
    )
    await client.post(
        "/api/tasks/",
        json={
            "task_id": "TEST-DEP-OVERRIDE-2",
            "title": "Task 2 depends on 1",
            "priority": "HIGH",
            "dependencies": "TEST-DEP-OVERRIDE-1",
            "instructions": "Test instructions",
            "estimated_effort": "1 hour",
        },
    )

    # Delete task with admin override
    delete_response = await client.delete("/api/tasks/TEST-DEP-OVERRIDE-1?admin_override=true")
    assert delete_response.status_code == 204

    # Verify task no longer exists
    verify_response = await client.get("/api/tasks/TEST-DEP-OVERRIDE-1")
    assert verify_response.status_code == 404


@pytest.mark.asyncio
async def test_create_task_with_session_id(client: AsyncClient) -> None:
    """Test creating a task with session_id."""
    response = await client.post(
        "/api/tasks/?session_id=manager-session-123",
        json={
            "task_id": "TEST-SESSION-1",
            "title": "Task with session",
            "priority": "HIGH",
            "estimated_effort": "2 hours",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["task_id"] == "TEST-SESSION-1"
    assert data["session_id"] == "manager-session-123"
    assert data["session_start_time"] is not None
    assert data["task_type"] == "feature"


@pytest.mark.asyncio
async def test_create_task_without_session_id(client: AsyncClient) -> None:
    """Test creating a task without session_id."""
    response = await client.post(
        "/api/tasks/",
        json={
            "task_id": "TEST-SESSION-2",
            "title": "Task without session",
            "priority": "MEDIUM",
            "estimated_effort": "1 hour",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["task_id"] == "TEST-SESSION-2"
    assert data["session_id"] is None
    assert data["session_start_time"] is None


@pytest.mark.asyncio
async def test_get_task_includes_session_fields(
    client: AsyncClient, sample_tasks: list[Task]
) -> None:
    """Test that task retrieval includes session fields."""
    response = await client.get("/api/tasks/TASK-101")
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "session_start_time" in data
    assert "task_type" in data


@pytest.mark.asyncio
async def test_search_no_filters(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test search with no filters returns all tasks with pagination."""
    response = await client.get("/api/tasks/search?page=1&page_size=5")
    assert response.status_code == 200
    data = response.json()
    assert "tasks" in data
    assert "pagination" in data
    assert len(data["tasks"]) <= 5
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["page_size"] == 5
    assert "total_count" in data["pagination"]
    assert "total_pages" in data["pagination"]


@pytest.mark.asyncio
async def test_search_by_task_id(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test search by exact task ID."""
    response = await client.get("/api/tasks/search?q=TASK-101")
    assert response.status_code == 200
    data = response.json()
    assert len(data["tasks"]) >= 1
    task_ids = [task["task_id"] for task in data["tasks"]]
    assert "TASK-101" in task_ids


@pytest.mark.asyncio
async def test_search_by_title(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test search by partial title match (case-insensitive)."""
    response = await client.get("/api/tasks/search?q=narrative")
    assert response.status_code == 200
    data = response.json()
    assert len(data["tasks"]) >= 1
    titles = [task["title"] for task in data["tasks"]]
    has_matching_title = any("narrative" in title.lower() for title in titles)
    assert has_matching_title


@pytest.mark.asyncio
async def test_search_by_task_type(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test search filtering by task type."""
    response = await client.get("/api/tasks/search?task_type=feature")
    assert response.status_code == 200
    data = response.json()
    for task in data["tasks"]:
        assert task["task_type"] == "feature"


@pytest.mark.asyncio
async def test_search_by_priority(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test search filtering by priority."""
    response = await client.get("/api/tasks/search?priority=HIGH")
    assert response.status_code == 200
    data = response.json()
    for task in data["tasks"]:
        assert task["priority"] == "HIGH"


@pytest.mark.asyncio
async def test_search_by_status(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test search filtering by status."""
    response = await client.get("/api/tasks/search?status=pending")
    assert response.status_code == 200
    data = response.json()
    for task in data["tasks"]:
        assert task["status"] == "pending"


@pytest.mark.asyncio
async def test_search_by_assigned_agent(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test search filtering by assigned agent."""
    response = await client.get("/api/tasks/search?assigned_agent=agent-1")
    assert response.status_code == 200
    data = response.json()
    for task in data["tasks"]:
        assert task["assigned_agent"] == "agent-1"


@pytest.mark.asyncio
async def test_search_invalid_priority(client: AsyncClient) -> None:
    """Test search with invalid priority returns 400."""
    response = await client.get("/api/tasks/search?priority=INVALID")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_search_pagination(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test search pagination with multiple pages."""
    response = await client.get("/api/tasks/search?page=1&page_size=2")
    assert response.status_code == 200
    data = response.json()
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["page_size"] == 2
    assert len(data["tasks"]) <= 2
    
    response = await client.get("/api/tasks/search?page=2&page_size=2")
    assert response.status_code == 200
    data = response.json()
    assert data["pagination"]["page"] == 2


@pytest.mark.asyncio
async def test_search_empty_results(client: AsyncClient) -> None:
    """Test search with no matching results returns empty list."""
    response = await client.get("/api/tasks/search?q=NONEXISTENT-TASK-XYZ")
    assert response.status_code == 200
    data = response.json()
    assert len(data["tasks"]) == 0
    assert data["pagination"]["total_count"] == 0


@pytest.mark.asyncio
async def test_search_special_characters(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test search handles special characters gracefully."""
    response = await client.get("/api/tasks/search?q=Test%20Task")
    assert response.status_code == 200
    data = response.json()
    assert "tasks" in data


@pytest.mark.asyncio
async def test_search_case_insensitive(client: AsyncClient, sample_tasks: list[Task]) -> None:
    """Test search is case-insensitive."""
    response1 = await client.get("/api/tasks/search?q=TASK-101")
    response2 = await client.get("/api/tasks/search?q=task-101")
    assert response1.status_code == 200
    assert response2.status_code == 200
    data1 = response1.json()
    data2 = response2.json()
    assert len(data1["tasks"]) == len(data2["tasks"])
