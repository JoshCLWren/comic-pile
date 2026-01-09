"""Local task cache for GitHub tasks with thread-safe operations."""

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CACHE_FILE = Path(".task_cache.json")
CACHE_TTL_SECONDS = 300
CACHE_LOCK = threading.RLock()


class TaskCache:
    """Thread-safe local cache for GitHub tasks."""

    def __init__(self, cache_file: Path = CACHE_FILE, ttl_seconds: int = CACHE_TTL_SECONDS) -> None:
        """Initialize the task cache.

        Args:
            cache_file: Path to cache file
            ttl_seconds: Time-to-live for cache entries in seconds
        """
        self.cache_file = cache_file
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, Any] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        """Load cache from disk."""
        with CACHE_LOCK:
            if self.cache_file.exists():
                try:
                    with open(self.cache_file) as f:
                        self._cache = json.load(f)
                    logger.debug(f"Loaded cache from {self.cache_file}")
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(f"Failed to load cache from {self.cache_file}: {e}")
                    self._cache = {}
            else:
                self._cache = {}

    def _save_cache(self) -> None:
        """Save cache to disk."""
        with CACHE_LOCK:
            try:
                with open(self.cache_file, "w") as f:
                    json.dump(self._cache, f, indent=2)
                logger.debug(f"Saved cache to {self.cache_file}")
            except OSError as e:
                logger.warning(f"Failed to save cache to {self.cache_file}: {e}")

    def _is_expired(self, timestamp: str) -> bool:
        """Check if a cache entry is expired.

        Args:
            timestamp: ISO format timestamp string

        Returns:
            True if expired, False otherwise
        """
        try:
            cached_time = datetime.fromisoformat(timestamp)
            age = (datetime.now(UTC) - cached_time).total_seconds()
            return age > self.ttl_seconds
        except (ValueError, TypeError):
            return True

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        """Get a task from cache by ID.

        Args:
            task_id: Task ID (GitHub issue number)

        Returns:
            Task dictionary or None if not found or expired
        """
        with CACHE_LOCK:
            task_key = f"task_{task_id}"
            if task_key in self._cache:
                task_data = self._cache[task_key]
                if not self._is_expired(task_data.get("cached_at", "")):
                    logger.debug(f"Cache hit for task {task_id}")
                    return task_data.get("task")
                else:
                    logger.debug(f"Cache expired for task {task_id}")
                    del self._cache[task_key]
            return None

    def set_task(self, task_id: int, task: dict[str, Any]) -> None:
        """Store a task in cache.

        Args:
            task_id: Task ID (GitHub issue number)
            task: Task dictionary to cache
        """
        with CACHE_LOCK:
            task_key = f"task_{task_id}"
            self._cache[task_key] = {
                "task": task,
                "cached_at": datetime.now(UTC).isoformat(),
            }
            self._save_cache()
            logger.debug(f"Cached task {task_id}")

    def get_all_tasks(self) -> list[dict[str, Any]]:
        """Get all non-expired tasks from cache.

        Returns:
            List of task dictionaries
        """
        with CACHE_LOCK:
            tasks = []
            expired_keys = []

            for key, value in self._cache.items():
                if key.startswith("task_"):
                    if not self._is_expired(value.get("cached_at", "")):
                        tasks.append(value["task"])
                    else:
                        expired_keys.append(key)

            for key in expired_keys:
                del self._cache[key]

            if expired_keys:
                self._save_cache()

            return tasks

    def update_task_status(self, task_id: int, status: str) -> None:
        """Update task status in cache.

        Args:
            task_id: Task ID (GitHub issue number)
            status: New status
        """
        with CACHE_LOCK:
            task_key = f"task_{task_id}"
            if task_key in self._cache:
                self._cache[task_key]["task"]["status"] = status
                self._cache[task_key]["cached_at"] = datetime.now(UTC).isoformat()
                self._save_cache()
                logger.debug(f"Updated status for cached task {task_id}: {status}")

    def invalidate_task(self, task_id: int) -> None:
        """Remove a task from cache.

        Args:
            task_id: Task ID (GitHub issue number)
        """
        with CACHE_LOCK:
            task_key = f"task_{task_id}"
            if task_key in self._cache:
                del self._cache[task_key]
                self._save_cache()
                logger.debug(f"Invalidated cache for task {task_id}")

    def clear(self) -> None:
        """Clear all cached tasks."""
        with CACHE_LOCK:
            self._cache = {}
            self._save_cache()
            logger.info("Cleared task cache")

    def get_pending_tasks(self) -> list[dict[str, Any]]:
        """Get all pending tasks from cache.

        Returns:
            List of pending task dictionaries
        """
        return [
            task
            for task in self.get_all_tasks()
            if task.get("status") in ("pending", "in-progress")
        ]

    def get_blocked_tasks(self) -> list[dict[str, Any]]:
        """Get all blocked tasks from cache.

        Returns:
            List of blocked task dictionaries
        """
        return [task for task in self.get_all_tasks() if task.get("status") == "blocked"]

    def is_available(self) -> bool:
        """Check if cache is available (offline capability).

        Returns:
            True if cache file exists and has data, False otherwise
        """
        with CACHE_LOCK:
            return self.cache_file.exists() and len(self._cache) > 0

    def sync_from_github(self, tasks: list[dict[str, Any]]) -> None:
        """Sync cache from GitHub tasks.

        Args:
            tasks: List of task dictionaries from GitHub
        """
        with CACHE_LOCK:
            for task in tasks:
                task_id = task.get("id")
                if task_id:
                    task_key = f"task_{task_id}"
                    self._cache[task_key] = {
                        "task": task,
                        "cached_at": datetime.now(UTC).isoformat(),
                    }
            self._save_cache()
            logger.info(f"Synced {len(tasks)} tasks from GitHub to cache")

    def get_cache_info(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        with CACHE_LOCK:
            total_tasks = 0
            expired_tasks = 0

            for key, value in self._cache.items():
                if key.startswith("task_"):
                    total_tasks += 1
                    if self._is_expired(value.get("cached_at", "")):
                        expired_tasks += 1

            return {
                "total_tasks": total_tasks,
                "expired_tasks": expired_tasks,
                "valid_tasks": total_tasks - expired_tasks,
                "cache_file": str(self.cache_file),
                "cache_exists": self.cache_file.exists(),
            }
