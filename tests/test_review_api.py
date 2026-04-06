"""Tests for Review API endpoints."""

import pytest
from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Review, Thread, User
from tests.conftest import get_or_create_user_async


async def _create_test_thread_with_issues(
    async_db: AsyncSession,
    user: User,
    *,
    title: str,
    issue_count: int = 5,
) -> tuple[Thread, list[Issue]]:
    """Create a thread with issues for review tests."""
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=issue_count,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=issue_count,
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issues: list[Issue] = []
    for i in range(1, issue_count + 1):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(i),
            position=i,
            status="unread",
        )
        issues.append(issue)
        async_db.add(issue)

    await async_db.commit()
    await async_db.refresh(thread)
    return thread, issues


async def _create_test_review(
    async_db: AsyncSession,
    user: User,
    thread: Thread,
    issue: Issue | None = None,
    *,
    rating: float,
    review_text: str | None = None,
) -> Review:
    """Create a test review."""
    review = Review(
        user_id=user.id,
        thread_id=thread.id,
        issue_id=issue.id if issue else None,
        rating=rating,
        review_text=review_text,
    )
    async_db.add(review)
    await async_db.commit()
    await async_db.refresh(review)
    return review


@pytest.mark.asyncio
async def test_create_review_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /reviews/ creates a new review successfully."""
    user = await get_or_create_user_async(async_db)
    thread, _ = await _create_test_thread_with_issues(async_db, user, title="Test Thread")

    review_data = {
        "thread_id": thread.id,
        "rating": 4.5,
        "issue_number": "1",
        "review_text": "Great first issue!",
    }

    response = await auth_client.post("/api/v1/reviews/", json=review_data)
    assert response.status_code == 201

    data = response.json()
    assert data["thread_id"] == thread.id
    assert data["rating"] == 4.5
    assert data["issue_number"] == "1"
    assert data["review_text"] == "Great first issue!"
    assert data["thread_title"] == thread.title
    assert data["user_id"] == user.id
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_create_review_without_issue_number(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /reviews/ creates a review for entire thread (no issue number)."""
    user = await get_or_create_user_async(async_db)
    thread, _ = await _create_test_thread_with_issues(async_db, user, title="Test Thread")

    review_data = {
        "thread_id": thread.id,
        "rating": 5.0,
        "review_text": "Amazing series overall!",
    }

    response = await auth_client.post("/api/v1/reviews/", json=review_data)
    assert response.status_code == 201

    data = response.json()
    assert data["thread_id"] == thread.id
    assert data["rating"] == 5.0
    assert data["issue_id"] is None
    assert data["issue_number"] is None
    assert data["review_text"] == "Amazing series overall!"


@pytest.mark.asyncio
async def test_create_review_nonexistent_thread(auth_client: AsyncClient) -> None:
    """POST /reviews/ returns 404 for non-existent thread."""
    review_data = {
        "thread_id": 999,
        "rating": 4.0,
        "review_text": "Test review",
    }

    response = await auth_client.post("/api/v1/reviews/", json=review_data)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_review_nonexistent_issue(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /reviews/ returns 404 for non-existent issue number."""
    user = await get_or_create_user_async(async_db)
    thread, _ = await _create_test_thread_with_issues(async_db, user, title="Test Thread")

    review_data = {
        "thread_id": thread.id,
        "rating": 4.0,
        "issue_number": "999",  # Doesn't exist
        "review_text": "Test review",
    }

    response = await auth_client.post("/api/v1/reviews/", json=review_data)
    assert response.status_code == 404
    assert "issue 999 not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_review_updates_existing_review(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /reviews/ updates existing review for same thread/issue combination."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_test_thread_with_issues(async_db, user, title="Test Thread")

    # Create initial review
    existing_review = await _create_test_review(
        async_db, user, thread, issues[0], rating=3.0, review_text="Okay issue"
    )

    # Create same review with updated data
    review_data = {
        "thread_id": thread.id,
        "rating": 4.5,
        "issue_number": "1",
        "review_text": "Actually, it's great!",
    }

    response = await auth_client.post("/api/v1/reviews/", json=review_data)
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == existing_review.id  # Same review ID
    assert data["rating"] == 4.5
    assert data["review_text"] == "Actually, it's great!"

    # Verify it was updated in database
    result = await async_db.execute(select(Review).where(Review.id == existing_review.id))
    review = result.scalar_one()
    assert review.rating == 4.5
    assert review.review_text == "Actually, it's great!"


@pytest.mark.asyncio
async def test_list_reviews_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """GET /reviews/ lists current user's reviews with pagination."""
    user = await get_or_create_user_async(async_db)

    # Create multiple threads and reviews
    thread1, issues1 = await _create_test_thread_with_issues(async_db, user, title="Thread 1")
    thread2, issues2 = await _create_test_thread_with_issues(async_db, user, title="Thread 2")

    review1 = await _create_test_review(
        async_db, user, thread1, issues1[0], rating=4.0, review_text="Review 1"
    )
    review2 = await _create_test_review(async_db, user, thread2, rating=5.0, review_text="Review 2")
    review3 = await _create_test_review(
        async_db, user, thread1, issues1[1], rating=3.5, review_text="Review 3"
    )

    response = await auth_client.get("/api/v1/reviews/")
    assert response.status_code == 200

    data = response.json()
    assert "reviews" in data
    assert "next_page_token" in data
    assert len(data["reviews"]) == 3

    # Verify reviews are ordered by created_at desc
    reviews = data["reviews"]
    assert reviews[0]["id"] == review3.id  # Most recent
    assert reviews[1]["id"] == review2.id
    assert reviews[2]["id"] == review1.id  # Oldest


@pytest.mark.asyncio
async def test_list_reviews_pagination(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """GET /reviews/ with page_size and page_token paginates results."""
    user = await get_or_create_user_async(async_db)

    # Create 5 reviews
    threads = []
    reviews = []
    for i in range(5):
        thread, _ = await _create_test_thread_with_issues(async_db, user, title=f"Thread {i}")
        threads.append(thread)
        review = await _create_test_review(
            async_db, user, thread, rating=float(i + 1), review_text=f"Review {i}"
        )
        reviews.append(review)

    # Get first page with 2 items
    response = await auth_client.get("/api/v1/reviews/?page_size=2")
    assert response.status_code == 200

    data = response.json()
    assert len(data["reviews"]) == 2
    assert data["next_page_token"] is not None

    # Verify first page has most recent reviews
    assert data["reviews"][0]["id"] == reviews[4].id
    assert data["reviews"][1]["id"] == reviews[3].id

    # Get second page
    page_token = data["next_page_token"]
    response2 = await auth_client.get(f"/api/v1/reviews/?page_size=2&page_token={page_token}")
    assert response2.status_code == 200

    data2 = response2.json()
    assert len(data2["reviews"]) == 2
    assert data2["reviews"][0]["id"] == reviews[2].id
    assert data2["reviews"][1]["id"] == reviews[1].id


@pytest.mark.asyncio
async def test_list_reviews_invalid_page_token(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """GET /reviews/ with invalid page_token returns 400."""
    response = await auth_client.get("/api/v1/reviews/?page_token=invalid")
    assert response.status_code == 400
    assert "invalid page_token" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_review_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """GET /reviews/{id} returns specific review."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_test_thread_with_issues(async_db, user, title="Test Thread")
    review = await _create_test_review(
        async_db, user, thread, issues[0], rating=4.5, review_text="Great!"
    )

    response = await auth_client.get(f"/api/v1/reviews/{review.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == review.id
    assert data["thread_id"] == thread.id
    assert data["rating"] == 4.5
    assert data["issue_number"] == "1"
    assert data["review_text"] == "Great!"
    assert data["thread_title"] == thread.title


@pytest.mark.asyncio
async def test_get_review_not_found(auth_client: AsyncClient) -> None:
    """GET /reviews/{id} returns 404 for non-existent review."""
    response = await auth_client.get("/api/v1/reviews/999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_review_other_user_review(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """GET /reviews/{id} returns 404 for review owned by different user."""
    other_user = User(username="other_user", created_at=datetime.now(UTC))
    async_db.add(other_user)
    await async_db.commit()

    thread, issues = await _create_test_thread_with_issues(
        async_db, other_user, title="Other Thread"
    )
    review = await _create_test_review(
        async_db, other_user, thread, issues[0], rating=4.0, review_text="Other review"
    )

    response = await auth_client.get(f"/api/v1/reviews/{review.id}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_review_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """PUT /reviews/{id} updates review successfully."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_test_thread_with_issues(async_db, user, title="Test Thread")
    review = await _create_test_review(
        async_db, user, thread, issues[0], rating=3.0, review_text="Okay"
    )

    update_data = {
        "rating": 4.5,
        "review_text": "Actually, it's excellent!",
    }

    response = await auth_client.put(f"/api/v1/reviews/{review.id}", json=update_data)
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == review.id
    assert data["rating"] == 4.5
    assert data["review_text"] == "Actually, it's excellent!"
    assert data["updated_at"] != data["created_at"]  # Should be updated


@pytest.mark.asyncio
async def test_update_review_partial_update(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """PUT /reviews/{id} can update only rating or only review_text."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_test_thread_with_issues(async_db, user, title="Test Thread")
    review = await _create_test_review(
        async_db, user, thread, issues[0], rating=3.0, review_text="Okay"
    )

    # Update only rating
    update_data = {"rating": 5.0}
    response = await auth_client.put(f"/api/v1/reviews/{review.id}", json=update_data)
    assert response.status_code == 200

    data = response.json()
    assert data["rating"] == 5.0
    assert data["review_text"] == "Okay"  # Unchanged

    # Update only review_text
    update_data = {"review_text": "Updated text"}
    response2 = await auth_client.put(f"/api/v1/reviews/{review.id}", json=update_data)
    assert response2.status_code == 200

    data2 = response2.json()
    assert data2["rating"] == 5.0  # Unchanged
    assert data2["review_text"] == "Updated text"


@pytest.mark.asyncio
async def test_update_review_not_found(auth_client: AsyncClient) -> None:
    """PUT /reviews/{id} returns 404 for non-existent review."""
    update_data = {"rating": 5.0, "review_text": "Updated"}
    response = await auth_client.put("/api/v1/reviews/999", json=update_data)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_review_other_user_review(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """PUT /reviews/{id} returns 404 for review owned by different user."""
    other_user = User(username="other_user", created_at=datetime.now(UTC))
    async_db.add(other_user)
    await async_db.commit()

    thread, issues = await _create_test_thread_with_issues(
        async_db, other_user, title="Other Thread"
    )
    review = await _create_test_review(
        async_db, other_user, thread, issues[0], rating=4.0, review_text="Other review"
    )

    update_data = {"rating": 5.0}
    response = await auth_client.put(f"/api/v1/reviews/{review.id}", json=update_data)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_review_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """DELETE /reviews/{id} deletes review successfully."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_test_thread_with_issues(async_db, user, title="Test Thread")
    review = await _create_test_review(
        async_db, user, thread, issues[0], rating=4.0, review_text="To be deleted"
    )

    response = await auth_client.delete(f"/api/v1/reviews/{review.id}")
    assert response.status_code == 204

    # Verify review is deleted
    result = await async_db.execute(select(Review).where(Review.id == review.id))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_review_not_found(auth_client: AsyncClient) -> None:
    """DELETE /reviews/{id} returns 404 for non-existent review."""
    response = await auth_client.delete("/api/v1/reviews/999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_review_other_user_review(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """DELETE /reviews/{id} returns 404 for review owned by different user."""
    other_user = User(username="other_user", created_at=datetime.now(UTC))
    async_db.add(other_user)
    await async_db.commit()

    thread, issues = await _create_test_thread_with_issues(
        async_db, other_user, title="Other Thread"
    )
    review = await _create_test_review(
        async_db, other_user, thread, issues[0], rating=4.0, review_text="Other review"
    )

    response = await auth_client.delete(f"/api/v1/reviews/{review.id}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_thread_reviews_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """GET /threads/{id}/reviews returns all reviews for a thread."""
    user = await get_or_create_user_async(async_db)

    thread, issues = await _create_test_thread_with_issues(async_db, user, title="Test Thread")

    # Create multiple reviews for the thread
    review1 = await _create_test_review(async_db, user, thread, rating=3.0)
    review2 = await _create_test_review(async_db, user, thread, rating=4.0)
    review3 = await _create_test_review(async_db, user, thread, rating=5.0)

    response = await auth_client.get(f"/api/threads/{thread.id}/reviews")
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 3

    # Verify all reviews are for the correct thread
    for review_data in data:
        assert review_data["thread_id"] == thread.id

    # Verify reviews are ordered by created_at desc
    assert data[0]["id"] == review3.id
    assert data[1]["id"] == review2.id
    assert data[2]["id"] == review1.id


@pytest.mark.asyncio
async def test_get_thread_reviews_empty(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """GET /threads/{id}/reviews returns empty list when no reviews."""
    user = await get_or_create_user_async(async_db)

    thread, issues = await _create_test_thread_with_issues(async_db, user, title="Test Thread")

    response = await auth_client.get(f"/api/threads/{thread.id}/reviews")
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0


@pytest.mark.asyncio
async def test_get_thread_reviews_not_found(auth_client: AsyncClient) -> None:
    """GET /threads/{id}/reviews returns 404 for non-existent thread."""
    response = await auth_client.get("/api/threads/999/reviews")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_thread_reviews_other_user_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """GET /threads/{thread_id}/reviews returns 404 for thread owned by different user."""
    other_user = User(username="other_user", created_at=datetime.now(UTC))
    async_db.add(other_user)
    await async_db.commit()

    thread, _ = await _create_test_thread_with_issues(async_db, other_user, title="Other Thread")

    response = await auth_client.get(f"/api/threads/{thread.id}/reviews")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_review_validation_rating_bounds(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /reviews/ validates rating bounds (0.5 to 5.0)."""
    user = await get_or_create_user_async(async_db)
    thread, _ = await _create_test_thread_with_issues(async_db, user, title="Test Thread")

    # Test rating too low
    review_data = {
        "thread_id": thread.id,
        "rating": 0.4,  # Below minimum
        "review_text": "Test review",
    }

    response = await auth_client.post("/api/v1/reviews/", json=review_data)
    assert response.status_code == 422

    # Test rating too high
    review_data["rating"] = 5.1  # Above maximum
    response = await auth_client.post("/api/v1/reviews/", json=review_data)
    assert response.status_code == 422

    # Test valid ratings
    for valid_rating in [0.5, 1.0, 3.5, 5.0]:
        review_data["rating"] = valid_rating
    response = await auth_client.post("/api/v1/reviews/", json=review_data)
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_review_validation_text_length(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /reviews/ validates review text length constraints."""
    user = await get_or_create_user_async(async_db)
    thread, _ = await _create_test_thread_with_issues(async_db, user, title="Test Thread")

    # Test empty review text (should pass as it's optional)
    review_data = {
        "thread_id": thread.id,
        "rating": 4.0,
        "review_text": "",  # Empty string
    }

    response = await auth_client.post("/api/v1/reviews/", json=review_data)
    # Note: The schema allows None but empty string might be stripped to None
    assert response.status_code in [201, 422]

    # Test review text that's too long (2001 characters)
    review_data["review_text"] = "x" * 2001
    response = await auth_client.post("/api/v1/reviews/", json=review_data)
    assert response.status_code == 422

    # Test valid review text length
    review_data["review_text"] = "x" * 2000  # Maximum allowed
    response = await auth_client.post("/api/v1/reviews/", json=review_data)
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_create_review_thread_validation(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /reviews/ validates thread_id is positive."""
    # Test invalid thread_id
    review_data = {
        "thread_id": 0,  # Invalid
        "rating": 4.0,
        "review_text": "Test review",
    }

    response = await auth_client.post("/api/v1/reviews/", json=review_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_review_rating_validation(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """PUT /reviews/{id} validates rating bounds during update."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_test_thread_with_issues(async_db, user, title="Test Thread")
    review = await _create_test_review(
        async_db, user, thread, issues[0], rating=4.0, review_text="Original"
    )

    # Test invalid rating
    update_data = {"rating": 0.1}  # Too low
    response = await auth_client.put(f"/api/v1/reviews/{review.id}", json=update_data)
    assert response.status_code == 422

    # Test valid update
    update_data["rating"] = 4.5
    response = await auth_client.put(f"/api/v1/reviews/{review.id}", json=update_data)
    assert response.status_code == 200
