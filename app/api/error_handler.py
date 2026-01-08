"""Automatic 5xx error handling and task creation system."""

import json
import logging
import traceback
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Request

logger = logging.getLogger(__name__)

TASKS_FILE = Path("tasks.json")

ERROR_COUNTER: dict[str, int] = {"total_5xx": 0}

KNOWN_5XX_ERRORS: dict[str, dict[str, str | bool | list[str]]] = {
    "database_connection_failed": {
        "create_task": True,
        "keywords": ["OperationalError", "database connection", "connection refused"],
        "priority": "HIGH",
        "estimated_effort": "2 hours",
    },
    "query_timeout": {
        "create_task": True,
        "keywords": ["timeout", "QueryTimeoutError", "statement timeout"],
        "priority": "HIGH",
        "estimated_effort": "2 hours",
    },
    "constraint_violation": {
        "create_task": True,
        "keywords": ["IntegrityError", "foreign key constraint", "unique constraint", "NOT NULL"],
        "priority": "HIGH",
        "estimated_effort": "1 hour",
    },
    "temporary_server_error": {
        "create_task": False,
        "keywords": ["temporary", "TransientError", "retry"],
        "priority": "LOW",
        "estimated_effort": "0 hours",
    },
}


def is_known_5xx_error(
    error: Exception, error_type: str, error_message: str
) -> tuple[bool, dict[str, str | bool | list[str]] | None]:
    """Check if error matches any known 5xx error patterns."""
    for _error_name, error_info in KNOWN_5XX_ERRORS.items():
        keywords = error_info.get("keywords", [])
        if isinstance(keywords, list):
            for keyword in keywords:
                if keyword in error_type or keyword.lower() in error_message.lower():
                    return True, error_info
    return False, None


def create_error_task(
    request_body: str | dict | list | None,
    path: str,
    http_method: str,
    path_params: dict[str, str],
    headers: dict[str, str],
    error: Exception,
    error_info: dict[str, str | bool | list[str]],
    request: Request,
) -> None:
    """Create a task in tasks.json with full debugging information."""
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    task_id = f"API-ERROR-{timestamp}"
    error_type = type(error).__name__

    task = {
        "task_id": task_id,
        "title": f"5xx Error: {error_type}",
        "description": {
            "request_body": request_body,
            "path": path,
            "http_method": http_method,
            "path_params": path_params,
            "headers": headers,
            "error": str(error),
            "traceback": traceback.format_exc(),
        },
        "priority": error_info.get("priority", "HIGH"),
        "status": "pending",
        "task_type": "bug",
        "estimated_effort": error_info.get("estimated_effort", "2 hours"),
        "instructions": (
            f"Investigate and fix {error_type} error. Check traceback for root cause and location."
        ),
    }

    if not TASKS_FILE.exists():
        tasks = {"tasks": []}
    else:
        with open(TASKS_FILE) as f:
            tasks = json.load(f)

    tasks["tasks"].append(task)

    with open(TASKS_FILE, "w") as f:
        json.dump(tasks, f, indent=2, default=str)

    logger.info(f"Created task {task_id} for 5xx error: {error_type}")


def handle_5xx_error(error: Exception, request: Request) -> dict[str, str]:
    """Handle 5xx errors by creating tasks or incrementing counter."""
    ERROR_COUNTER["total_5xx"] += 1

    error_type = type(error).__name__
    error_message = str(error)

    path = request.url.path
    http_method = request.method
    path_params = dict(request.path_params)
    headers = dict(request.headers)

    request_body = getattr(request.state, "request_body", None)

    is_known, error_info = is_known_5xx_error(error, error_type, error_message)

    if is_known and error_info and error_info.get("create_task", False):
        create_error_task(
            request_body, path, http_method, path_params, headers, error, error_info, request
        )
        logger.info(f"5xx error handled as known issue: {error_type}")
        return {"action": "task_created", "error_type": error_type}
    else:
        if is_known:
            logger.info(f"5xx error logged (known temporary error): {error_type}")
        else:
            logger.info(f"5xx error logged (unknown error): {error_type}")
        return {"action": "logged", "error_type": error_type}


def get_error_stats() -> dict[str, int]:
    """Get current error statistics."""
    return ERROR_COUNTER.copy()
