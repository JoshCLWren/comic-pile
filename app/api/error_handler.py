"""Automatic 5xx error handling and GitHub issue creation system."""

import logging
import traceback
from datetime import UTC, datetime

from fastapi import Request

logger = logging.getLogger(__name__)

ERROR_COUNTER: dict[str, int] = {"total_5xx": 0}

KNOWN_5XX_ERRORS: dict[str, dict[str, str | bool | list[str]]] = {
    "database_connection_failed": {
        "create_issue": True,
        "keywords": ["OperationalError", "database connection", "connection refused"],
        "priority": "high",
        "estimated_effort": "2 hours",
    },
    "query_timeout": {
        "create_issue": True,
        "keywords": ["timeout", "QueryTimeoutError", "statement timeout"],
        "priority": "high",
        "estimated_effort": "2 hours",
    },
    "constraint_violation": {
        "create_issue": True,
        "keywords": ["IntegrityError", "foreign key constraint", "unique constraint", "NOT NULL"],
        "priority": "high",
        "estimated_effort": "1 hour",
    },
    "temporary_server_error": {
        "create_issue": False,
        "keywords": ["temporary", "TransientError", "retry"],
        "priority": "low",
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


def create_github_issue(
    request_body: str | dict | list | None,
    path: str,
    http_method: str,
    path_params: dict[str, str],
    headers: dict[str, str],
    error: Exception,
    error_info: dict[str, str | bool | list[str]],
) -> None:
    """Create a GitHub issue with full debugging information."""
    try:
        from scripts.github_task_client import GitHubTaskClient

        client = GitHubTaskClient()

        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        error_type = type(error).__name__

        description = f"""## Error Details

**Error Type:** {error_type}
**Timestamp:** {timestamp}
**Path:** {http_method} {path}

## Request Information

**Path Parameters:**
```
{path_params}
```

**Headers:**
```
{headers}
```

**Request Body:**
```
{request_body}
```

## Error Message

```
{str(error)}
```

## Traceback

```
{traceback.format_exc()}
```

## Instructions

Investigate and fix this {error_type} error:
1. Check the traceback for the root cause and location
2. Identify the code path that triggered the error
3. Implement a fix to prevent this error
4. Add tests to prevent regression
5. Test the fix in a development environment

## Auto-Generated

This issue was automatically created by the error handler.
"""

        priority = error_info.get("priority", "high").lower()
        task_type = "bug"

        issue = client.create_task(
            title=f"5xx Error: {error_type}",
            description=description,
            priority=priority,
            task_type=task_type,
        )

        logger.info(f"Created GitHub issue #{issue['id']} for 5xx error: {error_type}")
    except Exception as e:
        logger.error(f"Failed to create GitHub issue for error: {e}")


def handle_5xx_error(error: Exception, request: Request) -> dict[str, str]:
    """Handle 5xx errors by creating GitHub issues or incrementing counter."""
    ERROR_COUNTER["total_5xx"] += 1

    error_type = type(error).__name__
    error_message = str(error)

    path = request.url.path
    http_method = request.method
    path_params = dict(request.path_params)
    headers = dict(request.headers)

    request_body = getattr(request.state, "request_body", None)

    is_known, error_info = is_known_5xx_error(error, error_type, error_message)

    if is_known and error_info and error_info.get("create_issue", False):
        create_github_issue(
            request_body, path, http_method, path_params, headers, error, error_info
        )
        logger.info(f"5xx error handled as known issue: {error_type}")
        return {"action": "issue_created", "error_type": error_type}
    else:
        if is_known:
            logger.info(f"5xx error logged (known temporary error): {error_type}")
        else:
            logger.info(f"5xx error logged (unknown error): {error_type}")
        return {"action": "logged", "error_type": error_type}


def get_error_stats() -> dict[str, int]:
    """Get current error statistics."""
    return ERROR_COUNTER.copy()
