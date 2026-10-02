"""Architecture guard for reading-session naming (issue #2998).

This test ensures that authentication/password-reset code cannot accidentally
call destructive reading-session helpers. It acts as a static guard that will
fail if auth code imports reading-session repositories or helpers.

The guard is intentionally simple and dependency-free so it runs in CI without
a database.
"""

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AUTH_MODULES = {
    REPOSITORY_ROOT / "app" / "auth.py",
    REPOSITORY_ROOT / "app" / "api" / "auth.py",
    REPOSITORY_ROOT / "app" / "services" / "password_reset_service.py",
}


READING_SESSION_REPOSITORY_PATTERNS = [
    "reading_session_repository",
    "ReadingSessionRepository",
    "get_reading_session",
    "find_owned_reading_session",
    "fetch_active_reading_session",
    "fetch_reading_history_page",
    "restore_reading_session_start",
    "detach_pending_thread_references_from_reading_sessions",
    "null_event_thread_references",
    "count_snapshots",
    "snapshot_counts_by_reading_session",
    "snapshots_desc",
    "first_start_snapshot",
    "latest_action_event",
    "latest_roll_event",
    "events_chronological",
    "recent_reading_session_events",
    "recent_snooze_events",
    "die_change_events",
    "history_events_for_reading_sessions",
]


READING_SESSION_SERVICE_PATTERNS = [
    "reading_session_service",
    "ReadingSessionService",
]

READING_SESSION_MODEL_PATTERNS = [
    "from app.models import ReadingSession",
    "from app.models.reading_session import ReadingSession",
    "import app.models.reading_session",
]


def _scan_module_for_patterns(module_path: Path, patterns: list[str]) -> list[str]:
    """Scan a Python module for forbidden import/call patterns.

    Returns a list of matched patterns with line numbers.
    """
    matches: list[str] = []
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            for alias in node.names:
                full_name = f"{module_name}.{alias.name}" if module_name else alias.name
                for pattern in patterns:
                    if pattern in full_name or pattern == alias.name:
                        matches.append(f"{module_path}:{node.lineno}: imports {full_name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                for pattern in patterns:
                    if pattern in alias.name:
                        matches.append(f"{module_path}:{node.lineno}: imports module {alias.name}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in patterns:
                    matches.append(f"{module_path}:{node.lineno}: calls {node.func.attr}")
            elif isinstance(node.func, ast.Name):
                if node.func.id in patterns:
                    matches.append(f"{module_path}:{node.lineno}: calls {node.func.id}")

    return matches


def test_auth_code_does_not_import_reading_session_repository() -> None:
    """Auth modules must not import reading-session repository helpers.

    If this test fails, it means auth code is attempting to call reading-session
    persistence logic, which would violate the domain boundary established in
    issue #2998. The fix is to remove the import/call and use the appropriate
    auth-domain helpers instead.
    """
    all_matches: list[str] = []
    all_patterns = (
        READING_SESSION_REPOSITORY_PATTERNS
        + READING_SESSION_SERVICE_PATTERNS
        + READING_SESSION_MODEL_PATTERNS
    )

    for module_path in AUTH_MODULES:
        if module_path.exists():
            matches = _scan_module_for_patterns(module_path, all_patterns)
            all_matches.extend(matches)

    assert not all_matches, (
        "Auth code must not import or call reading-session repository/service/model helpers. "
        "This would violate the domain boundary (issue #2998).\n"
        + "\n".join(all_matches)
    )


def test_reading_session_repository_docstring_mentions_auth_boundary() -> None:
    """Reading session repository must document its auth boundary."""
    repo_path = REPOSITORY_ROOT / "app" / "repositories" / "reading_session_repository.py"
    content = repo_path.read_text(encoding="utf-8")
    assert "authentication state" in content or "auth session" in content.lower() or "login" in content.lower(), (
        "reading_session_repository.py must document that it does not touch authentication state"
    )


def test_password_reset_service_docstring_mentions_reading_sessions_survive() -> None:
    """Password reset service must document that reading sessions survive reset."""
    service_path = REPOSITORY_ROOT / "app" / "services" / "password_reset_service.py"
    content = service_path.read_text(encoding="utf-8")
    assert "reading-history table is never touched" in content or "reading sessions survive" in content.lower(), (
        "password_reset_service.py must document that reading sessions survive password reset"
    )