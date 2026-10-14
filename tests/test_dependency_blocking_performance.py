"""Performance test for optimized get_thread_blocking_info endpoint."""

import time
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.dependency_service import get_thread_blocking_info
from app.schemas.dependency import BlockingExplanation


async def test_get_thread_blocking_info_performance_optimized(
    auth_client, async_db, test_username
):
    """Test that the optimized get_thread_blocking_info endpoint performs better."""
    user_result = await async_db.execute("SELECT id FROM users WHERE username = :username", {"username": test_username})
    user = user_result.scalar_one()
    
    # Create multiple threads and issues to create a complex dependency scenario
    threads = []
    issues = []
    
    # Create source thread
    source_thread = await async_db.execute(
        "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id, total_issues) "
        "VALUES (:title, :format, :issues_remaining, :queue_position, :status, :user_id, :total_issues) "
        "RETURNING *",
        {
            "title": "Source Thread",
            "format": "Comic", 
            "issues_remaining": 1,
            "queue_position": 1,
            "status": "active",
            "user_id": user.id,
            "total_issues": 1
        }
    )
    source_thread = source_thread.fetchone()
    threads.append(source_thread)
    
    # Create target threads
    for i in range(5):
        target_thread = await async_db.execute(
            "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id, total_issues) "
            "VALUES (:title, :format, :issues_remaining, :queue_position, :status, :user_id, :total_issues) "
            "RETURNING *",
            {
                "title": f"Target Thread {i}",
                "format": "Comic",
                "issues_remaining": 3,
                "queue_position": i + 2,
                "status": "active", 
                "user_id": user.id,
                "total_issues": 3
            }
        )
        target_thread = target_thread.fetchone()
        threads.append(target_thread)
    
    # Create source issue
    source_issue = await async_db.execute(
        "INSERT INTO issues (thread_id, issue_number, position, status) "
        "VALUES (:thread_id, :issue_number, :position, :status) "
        "RETURNING *",
        {
            "thread_id": source_thread.id,
            "issue_number": "1",
            "position": 1,
            "status": "unread"
        }
    )
    source_issue = source_issue.fetchone()
    issues.append(source_issue)
    
    # Create target issues and set up next_unread_issue_id
    for i, thread in enumerate(threads[1:], 1):  # Skip source thread
        for j in range(3):
            target_issue = await async_db.execute(
                "INSERT INTO issues (thread_id, issue_number, position, status) "
                "VALUES (:thread_id, :issue_number, :position, :status) "
                "RETURNING *",
                {
                    "thread_id": thread.id,
                    "issue_number": str(j + 1),
                    "position": j + 1,
                    "status": "unread"
                }
            )
            target_issue = target_issue.fetchone()
            issues.append(target_issue)
            
            # Set the first issue as next_unread for each thread
            if j == 0:
                await async_db.execute(
                    "UPDATE threads SET next_unread_issue_id = :issue_id WHERE id = :thread_id",
                    {"issue_id": target_issue.id, "thread_id": thread.id}
                )
    
    await async_db.commit()
    
    # Create dependencies to make the blocking check complex
    for i, thread in enumerate(threads[1:], 1):  # Skip source thread
        # Create a dependency from source issue to the second issue in each target thread
        target_issue = await async_db.execute(
            "SELECT id FROM issues WHERE thread_id = :thread_id AND position = 2",
            {"thread_id": thread.id}
        )
        target_issue = target_issue.fetchone()
        
        if target_issue:
            await async_db.execute(
                "INSERT INTO dependencies (source_issue_id, target_issue_id, note) "
                "VALUES (:source_issue_id, :target_issue_id, NULL)",
                {
                    "source_issue_id": source_issue.id,
                    "target_issue_id": target_issue.id
                }
            )
    
    await async_db.commit()
    
    # Test the performance of the endpoint
    start_time = time.time()
    
    # Make the API call
    response = await auth_client.post(f"/api/v1/threads/{threads[1].id}:getBlockingInfo")
    
    end_time = time.time()
    duration_ms = (end_time - start_time) * 1000
    
    print(f"get_thread_blocking_info took {duration_ms:.2f}ms")
    
    # Verify the response
    assert response.status_code == 200
    data = response.json()
    assert data["is_blocked"] is True
    assert len(data["blocking_reasons"]) > 0
    assert len(data["blocking_dependencies"]) > 0
    
    # Performance assertion: should complete within 500ms (well under the 1000ms budget)
    assert duration_ms < 500, f"Endpoint took {duration_ms:.2f}ms, expected under 500ms"


async def test_get_thread_blocking_info_correctness_unblocked(
    auth_client, async_db, test_username
):
    """Test that the optimized endpoint returns correct results for unblocked threads."""
    user_result = await async_db.execute("SELECT id FROM users WHERE username = :username", {"username": test_username})
    user = user_result.scalar_one()
    
    # Create an unblocked thread
    thread_result = await async_db.execute(
        "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id, total_issues) "
        "VALUES (:title, :format, :issues_remaining, :queue_position, :status, :user_id, :total_issues) "
        "RETURNING *",
        {
            "title": "Unblocked Thread",
            "format": "Comic",
            "issues_remaining": 1,
            "queue_position": 1,
            "status": "active",
            "user_id": user.id,
            "total_issues": 1
        }
    )
    thread = thread_result.fetchone()
    
    # Create an issue and set it as next_unread
    issue_result = await async_db.execute(
        "INSERT INTO issues (thread_id, issue_number, position, status) "
        "VALUES (:thread_id, :issue_number, :position, :status) "
        "RETURNING *",
        {
            "thread_id": thread.id,
            "issue_number": "1",
            "position": 1,
            "status": "unread"
        }
    )
    issue = issue_result.fetchone()
    
    await async_db.execute(
        "UPDATE threads SET next_unread_issue_id = :issue_id WHERE id = :thread_id",
        {"issue_id": issue.id, "thread_id": thread.id}
    )
    
    await async_db.commit()
    
    # Test the endpoint
    response = await auth_client.post(f"/api/v1/threads/{thread.id}:getBlockingInfo")
    
    assert response.status_code == 200
    data = response.json()
    assert data["is_blocked"] is False
    assert data["blocking_reasons"] == []
    assert data["blocking_dependencies"] == []


async def test_get_thread_blocking_info_correctness_blocked(
    auth_client, async_db, test_username
):
    """Test that the optimized endpoint returns correct results for blocked threads."""
    user_result = await async_db.execute("SELECT id FROM users WHERE username = :username", {"username": test_username})
    user = user_result.scalar_one()
    
    # Create source thread
    source_thread_result = await async_db.execute(
        "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id, total_issues) "
        "VALUES (:title, :format, :issues_remaining, :queue_position, :status, :user_id, :total_issues) "
        "RETURNING *",
        {
            "title": "Source Thread",
            "format": "Comic",
            "issues_remaining": 1,
            "queue_position": 1,
            "status": "active",
            "user_id": user.id,
            "total_issues": 1
        }
    )
    source_thread = source_thread_result.fetchone()
    
    # Create target thread
    target_thread_result = await async_db.execute(
        "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id, total_issues) "
        "VALUES (:title, :format, :issues_remaining, :queue_position, :status, :user_id, :total_issues) "
        "RETURNING *",
        {
            "title": "Target Thread",
            "format": "Comic",
            "issues_remaining": 2,
            "queue_position": 2,
            "status": "active",
            "user_id": user.id,
            "total_issues": 2
        }
    )
    target_thread = target_thread_result.fetchone()
    
    # Create source issue
    source_issue_result = await async_db.execute(
        "INSERT INTO issues (thread_id, issue_number, position, status) "
        "VALUES (:thread_id, :issue_number, :position, :status) "
        "RETURNING *",
        {
            "thread_id": source_thread.id,
            "issue_number": "1",
            "position": 1,
            "status": "unread"
        }
    )
    source_issue = source_issue_result.fetchone()
    
    # Create target issues
    target_issue_1_result = await async_db.execute(
        "INSERT INTO issues (thread_id, issue_number, position, status) "
        "VALUES (:thread_id, :issue_number, :position, :status) "
        "RETURNING *",
        {
            "thread_id": target_thread.id,
            "issue_number": "1",
            "position": 1,
            "status": "unread"
        }
    )
    target_issue_1 = target_issue_1_result.fetchone()
    
    target_issue_2_result = await async_db.execute(
        "INSERT INTO issues (thread_id, issue_number, position, status) "
        "VALUES (:thread_id, :issue_number, :position, :status) "
        "RETURNING *",
        {
            "thread_id": target_thread.id,
            "issue_number": "2",
            "position": 2,
            "status": "unread"
        }
    )
    target_issue_2 = target_issue_2_result.fetchone()
    
    # Set up next_unread_issue_id
    await async_db.execute(
        "UPDATE threads SET next_unread_issue_id = :issue_id WHERE id = :thread_id",
        {"issue_id": target_issue_1.id, "thread_id": target_thread.id}
    )
    
    await async_db.commit()
    
    # Create a dependency that will block the target thread
    await async_db.execute(
        "INSERT INTO dependencies (source_issue_id, target_issue_id, note) "
        "VALUES (:source_issue_id, :target_issue_id, NULL)",
        {
            "source_issue_id": source_issue.id,
            "target_issue_id": target_issue_2.id
        }
    )
    
    await async_db.commit()
    
    # Test the endpoint
    response = await auth_client.post(f"/api/v1/threads/{target_thread.id}:getBlockingInfo")
    
    assert response.status_code == 200
    data = response.json()
    assert data["is_blocked"] is True
    assert len(data["blocking_reasons"]) > 0
    assert len(data["blocking_dependencies"]) > 0
    
    # Verify the blocking reason contains expected information
    blocking_reason = data["blocking_reasons"][0]
    assert "Source Thread" in blocking_reason
    assert "#1" in blocking_reason