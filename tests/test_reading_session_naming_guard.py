"""Architecture guard for reading-session naming (issue #2998).

These tests are pure static analysis: no database, no imports of application
modules. They exist so the destructive reading-history foot gun fixed in
#2996 (``delete_all_sessions_for_user()`` deleting reading rows from auth
recovery) cannot come back through a rename, a new helper, or a new auth import.
"""

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AUTH_MODULES = (
    REPOSITORY_ROOT / "app" / "auth.py",
    REPOSITORY_ROOT / "app" / "api" / "auth.py",
    REPOSITORY_ROOT / "app" / "services" / "password_reset_service.py",
    REPOSITORY_ROOT / "services" / "password_reset_mailer.py",
    REPOSITORY_ROOT / "repositories" / "user_repository.py",
    REPOSITORY_ROOT / "repositories" / "revoked_token_repository.py",
    REPOSITORY_ROOT / "repositories" / "password_reset_token_repository.py",
    REPOSITORY_ROOT / "repositories" / "failed_login_repository.py",
)

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
    "get_reading_session_service",
]

READING_SESSION_MODEL_PATTERNS = [
    "app.models.reading_session",
    "ReadingSession",
    "SessionModel",
]

READING_SESSION_REPOSITORY_MODULE = (
    REPOSITORY_ROOT / "app" / "repositories" / "reading_session_repository.py"
)


def _scan_module_for_patterns(module_path: Path, patterns: list[str]) -> list[str]:
    """Report imports and calls in one module that touch forbidden patterns.

    Args:
        module_path: Python file to parse.
        patterns: Forbidden dotted-module fragments, imported names, and
            called function or attribute names.

    Returns:
        Human-readable findings, each prefixed with ``path:lineno``.
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
                    if pattern in full_name or pattern in alias.name:
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


def test_auth_code_does_not_touch_reading_session_domain() -> None:
    """Auth and password-reset modules must not reach into the reading domain.

    A finding here means auth code is calling reading-history persistence, which
    is the exact defect from the #2996 password-reset incident. Auth recovery
    revokes credentials through ``password_changed_at``, ``revoked_tokens``, and
    ``password_reset_tokens`` only. Reading history belongs in
    ``app/services/reading_session_service.py`` and friends, so a legitimate
    cross-domain interaction belongs in a service that owns both sides, never
    inside an auth module.
    """
    findings: list[str] = []
    for module_path in AUTH_MODULES:
        if module_path.exists():
            findings.extend(_scan_module_for_patterns(module_path, READING_SESSION_MODEL_PATTERNS))
    for module_path in AUTH_MODULES:
        if module_path.exists():
            findings.extend(
                _scan_module_for_patterns(
                    module_path,
                    READING_SESSION_REPOSITORY_PATTERNS + READING_SESSION_SERVICE_PATTERNS,
                )
            )

    assert not findings, (
        "Auth code must not import or call reading-session repository/service/model "
        "helpers. Revoke credentials with auth-domain state instead (issue #2998).\n"
        + "\n".join(findings)
    )


def test_reading_session_repository_exposes_no_destructive_helper() -> None:
    """The reading-session repository must not offer a bulk delete helper.

    ``delete_all_sessions_for_user()`` was the ambiguous helper that auth
    recovery called during the #2996 incident. No public ``delete_*`` helper may
    reappear in this module: destructive reading-history operations, if ever
    needed, must be named for what they delete.
    """
    tree = ast.parse(READING_SESSION_REPOSITORY_MODULE.read_text(encoding="utf-8"))

    public_deleters = sorted(
        node.name
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and not node.name.startswith("_")
        and node.name.startswith("delete")
    )
    assert not public_deleters, (
        "reading_session_repository.py must not expose a bulk delete helper "
        f"(issue #2998): {public_deleters}"
    )

    for node in ast.walk(tree):
        if isinstance(node, ast.Delete):
            offenders = [
                target.id
                for target in node.targets
                if isinstance(target, ast.Name) and target.id == "ReadingSession"
            ]
            assert not offenders, (
                f"{READING_SESSION_REPOSITORY_MODULE}:{node.lineno} must not issue a bulk "
                "DELETE against reading sessions (issue #2998)"
            )


def test_reading_session_is_not_exposed_under_a_bare_session_name() -> None:
    """Application code must not import the reading model as bare ``Session``.

    The reading-history model is ``ReadingSession`` internally and stays the
    ``sessions`` table at the storage edge only. Re-exporting a bare ``Session``
    from ``app.models`` re-creates the autocomplete ambiguity this issue closed.
    """
    models_init = (REPOSITORY_ROOT / "app" / "models" / "__init__.py").read_text(encoding="utf-8")
    assert not (REPOSITORY_ROOT / "app" / "models" / "session.py").exists(), (
        "app/models/session.py must not return; the reading model is "
        "app/models/reading_session.py (issue #2998)"
    )

    tree = ast.parse(models_init)
    exported: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            continue
        if isinstance(node.value, (ast.List, ast.Tuple)):
            exported.update(
                element.value
                for element in node.value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            )
    assert "ReadingSession" in exported, "app.models must export ReadingSession"
    assert "Session" not in exported, (
        "app.models must not export a bare `Session` reading-history name (issue #2998)"
    )

    user_tree = ast.parse(
        (REPOSITORY_ROOT / "app" / "models" / "user.py").read_text(encoding="utf-8")
    )
    user_class = next(
        (
            node
            for node in user_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "User"
        ),
        None,
    )
    assert user_class is not None, "app/models/user.py must still declare the User model"

    mapped_names = {
        node.target.id
        for node in ast.walk(user_class)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and isinstance(node.annotation, ast.Subscript)
        and isinstance(node.annotation.value, ast.Name)
        and node.annotation.value.id == "Mapped"
    }
    assert "reading_sessions" in mapped_names, (
        "User must expose the reading-history relationship as `reading_sessions` (issue #2998)"
    )
    assert "sessions" not in mapped_names, (
        "User must not expose an ambiguous `sessions` relationship (issue #2998)"
    )


def test_password_reset_service_documents_that_reading_history_survives() -> None:
    """Password reset must document that reading sessions survive a reset."""
    service_path = REPOSITORY_ROOT / "app" / "services" / "password_reset_service.py"
    content = service_path.read_text(encoding="utf-8")
    assert "reading-history table is never touched" in content or "reading sessions survive" in content.lower(), (
        "password_reset_service.py must document that reading sessions survive password reset"
    )


def test_reading_session_repository_documents_its_auth_boundary() -> None:
    """The reading-session repository must state that it never touches auth state."""
    content = READING_SESSION_REPOSITORY_MODULE.read_text(encoding="utf-8")
    assert "authentication state" in content.lower(), (
        "reading_session_repository.py must document that it does not touch authentication state"
    )