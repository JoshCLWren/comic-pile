"""Tests for task cache."""

import sys
import pytest

sys.path.insert(0, "/home/josh/code/comic-pile")
from scripts.task_cache import TaskCache


@pytest.fixture
def temp_cache_file(tmp_path):
    """Create temporary cache file."""
    cache_file = tmp_path / ".task_cache.json"
    yield cache_file
    if cache_file.exists():
        cache_file.unlink()


@pytest.fixture
def sample_task():
    """Sample task for testing."""
    return {
        "id": 123,
        "title": "Test Task",
        "status": "pending",
        "priority": "high",
        "task_type": "feature",
        "description": "Test description",
    }


class TestTaskCache:
    """Test task cache functionality."""

    def test_initialization(self, temp_cache_file):
        """Test cache initialization."""
        cache = TaskCache(cache_file=temp_cache_file, ttl_seconds=60)
        assert cache.cache_file == temp_cache_file
        assert cache.ttl_seconds == 60

    def test_set_and_get_task(self, temp_cache_file, sample_task):
        """Test setting and getting task from cache."""
        cache = TaskCache(cache_file=temp_cache_file, ttl_seconds=60)

        cache.set_task(123, sample_task)

        retrieved = cache.get_task(123)
        assert retrieved is not None
        assert retrieved["id"] == 123
        assert retrieved["title"] == "Test Task"

    def test_get_nonexistent_task(self, temp_cache_file):
        """Test getting non-existent task returns None."""
        cache = TaskCache(cache_file=temp_cache_file, ttl_seconds=60)

        retrieved = cache.get_task(999)
        assert retrieved is None

    def test_task_expiry(self, temp_cache_file, sample_task):
        """Test task expires after TTL."""
        cache = TaskCache(cache_file=temp_cache_file, ttl_seconds=1)

        cache.set_task(123, sample_task)

        retrieved = cache.get_task(123)
        assert retrieved is not None

        import time

        time.sleep(1.1)

        retrieved = cache.get_task(123)
        assert retrieved is None

    def test_get_all_tasks(self, temp_cache_file, sample_task):
        """Test getting all tasks from cache."""
        cache = TaskCache(cache_file=temp_cache_file, ttl_seconds=60)

        cache.set_task(123, sample_task)
        cache.set_task(124, {**sample_task, "id": 124})

        tasks = cache.get_all_tasks()
        assert len(tasks) == 2

    def test_get_pending_tasks(self, temp_cache_file, sample_task):
        """Test getting pending tasks from cache."""
        cache = TaskCache(cache_file=temp_cache_file, ttl_seconds=60)

        cache.set_task(123, {**sample_task, "status": "pending"})
        cache.set_task(124, {**sample_task, "id": 124, "status": "done"})
        cache.set_task(125, {**sample_task, "id": 125, "status": "in-progress"})

        pending = cache.get_pending_tasks()
        assert len(pending) == 2
        assert all(t["status"] in ("pending", "in-progress") for t in pending)

    def test_get_blocked_tasks(self, temp_cache_file, sample_task):
        """Test getting blocked tasks from cache."""
        cache = TaskCache(cache_file=temp_cache_file, ttl_seconds=60)

        cache.set_task(123, {**sample_task, "status": "blocked"})
        cache.set_task(124, {**sample_task, "id": 124, "status": "pending"})

        blocked = cache.get_blocked_tasks()
        assert len(blocked) == 1
        assert blocked[0]["status"] == "blocked"

    def test_update_task_status(self, temp_cache_file, sample_task):
        """Test updating task status in cache."""
        cache = TaskCache(cache_file=temp_cache_file, ttl_seconds=60)

        cache.set_task(123, sample_task)
        cache.update_task_status(123, "done")

        retrieved = cache.get_task(123)
        assert retrieved is not None
        assert retrieved["status"] == "done"

    def test_invalidate_task(self, temp_cache_file, sample_task):
        """Test invalidating task from cache."""
        cache = TaskCache(cache_file=temp_cache_file, ttl_seconds=60)

        cache.set_task(123, sample_task)
        assert cache.get_task(123) is not None

        cache.invalidate_task(123)
        assert cache.get_task(123) is None

    def test_clear(self, temp_cache_file, sample_task):
        """Test clearing all tasks from cache."""
        cache = TaskCache(cache_file=temp_cache_file, ttl_seconds=60)

        cache.set_task(123, sample_task)
        cache.set_task(124, {**sample_task, "id": 124})

        assert len(cache.get_all_tasks()) == 2

        cache.clear()

        assert len(cache.get_all_tasks()) == 0

    def test_is_available(self, temp_cache_file):
        """Test checking if cache is available."""
        cache = TaskCache(cache_file=temp_cache_file, ttl_seconds=60)

        assert cache.is_available() is False

        cache.set_task(123, {"id": 123, "title": "Test"})

        assert cache.is_available() is True

    def test_sync_from_github(self, temp_cache_file, sample_task):
        """Test syncing from GitHub tasks."""
        cache = TaskCache(cache_file=temp_cache_file, ttl_seconds=60)

        tasks = [sample_task, {**sample_task, "id": 124}]
        cache.sync_from_github(tasks)

        assert len(cache.get_all_tasks()) == 2

    def test_get_cache_info(self, temp_cache_file, sample_task):
        """Test getting cache information."""
        cache = TaskCache(cache_file=temp_cache_file, ttl_seconds=60)

        cache.set_task(123, sample_task)

        import time

        time.sleep(1)

        cache.set_task(124, {**sample_task, "id": 124})

        info = cache.get_cache_info()
        assert "total_tasks" in info
        assert "expired_tasks" in info
        assert "valid_tasks" in info
        assert info["total_tasks"] == 2

    def test_cache_persistence(self, temp_cache_file, sample_task):
        """Test cache persists across instances."""
        cache1 = TaskCache(cache_file=temp_cache_file, ttl_seconds=60)
        cache1.set_task(123, sample_task)

        cache2 = TaskCache(cache_file=temp_cache_file, ttl_seconds=60)
        retrieved = cache2.get_task(123)

        assert retrieved is not None
        assert retrieved["id"] == 123

    def test_concurrent_access(self, temp_cache_file, sample_task):
        """Test concurrent access to cache."""
        import threading

        cache = TaskCache(cache_file=temp_cache_file, ttl_seconds=60)

        def set_task(task_id):
            cache.set_task(task_id, {**sample_task, "id": task_id})

        threads = [threading.Thread(target=set_task, args=(i,)) for i in range(10)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert len(cache.get_all_tasks()) == 10
