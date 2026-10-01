"""Regression coverage for the reading-session/auth-session boundary (#2998).

The password-reset incident fixed in #2996 happened because authentication code
called ``delete_all_sessions_for_user()``, a helper that actually deleted rows
from the ``sessions`` table -- durable *reading* history, not login state. These
tests lock both halves of the fix in place:

1. Password completion preserves populated reading history.
2. No authentication module may import a reading-session repository helper, and
   no destructive reading-session bulk-delete helper may exist at all.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password, verify_password
from app.models import Event, ReadingSession, Snapshot, Thread, User
from app.repositories.user_repository import create_user
from app.services.password_reset_service import complete_reset, request_forgot_password

REPO_ROOT = Path(__file__).resolve().parents[1]

# Modules that implement authentication and credential lifecycle. Reading-session
# persistence is not among their responsibilities.
AUTH_MODULES = (
    "app/auth.py",
    "app/services/password_reset_service.py",
    "app/repositories/password_reset_token_repository.py",
    "app/repositories/revoked_token_repository.py",
)

READING_SESSION_REPOSITORY_MODULE = "app/repositories/reading_session_repository.py"


async def _seed_reading_history(db: AsyncSession, user: User) -> tuple[int, int, int]:
    """Give the user a reading session with a thread, an event, and a snapshot.

    Returns:
        Tuple of (reading_session_id, thread_id, event_id).
    """
    thread = Thread(
        title="History Thread",
        format="Comic",
        issues_remaining=4,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    await db.flush()

    reading_session = ReadingSession(start_die=6, user_id=user.id)
    db.add(reading_session)
    await db.flush()

    event = Event(type="roll", session_id=reading_session.id, thread_id=thread.id)
    db.add(event)
    await db.flush()

    snapshot = Snapshot(
        session_id=reading_session.id,
        thread_states={thread.id: {"title": thread.title}},
        description="Session start",
    )
    db.add(snapshot)
    await db.commit()
    return reading_session.id, thread.id, event.id


@pytest.mark.asyncio
async def test_password_reset_preserves_reading_history(async_db: AsyncSession) -> None:
    """Completing a password reset must not delete reading history.

    Reading history survives a credential change; only credential material and
    ``password_changed_at`` change.
    """
    user = await create_user(
        async_db,
        username="historykeeper",
        email="historykeeper@example.com",
        password_hash=hash_password("old-password"),
    )
    await async_db.commit()

    session_id, thread_id, event_id = await _seed_reading_history(async_db, user)

    handoff = await request_forgot_password(async_db, "historykeeper@example.com")
    assert handoff is not None
    await complete_reset(async_db, handoff.reset_token, "new-password")

    await async_db.refresh(user)

    surviving_session = await async_db.get(ReadingSession, session_id)
    assert surviving_session is not None, "password reset deleted reading history"
    assert await async_db.get(Thread, thread_id) is not None
    assert await async_db.get(Event, event_id) is not None

    assert (
        await async_db.execute(
            select(func.count())
            .select_from(Snapshot)
            .where(Snapshot.session_id == session_id)
        )
    ).scalar_one() == 1

    # Credential state genuinely changed.
    assert user.password_changed_at is not None
    assert verify_password("new-password", user.password_hash)
    assert not verify_password("old-password", user.password_hash)


@pytest.mark.asyncio
async def test_password_reset_does_not_leave_session_free_for_auth(async_db: AsyncSession) -> None:
    """A second reset round leaves reading history intact and still rotates credentials."""
    user = await create_user(
        async_db,
        username="historykeeper2",
        email="historykeeper2@example.com",
        password_hash=hash_password("first-password"),
    )
    await async_db.commit()

    session_id, _, _ = await _seed_reading_history(async_db, user)

    for new_password in ("second-password", "third-password"):
        handoff = await request_forgot_password(async_db, "historykeeper2@example.com")
        assert handoff is not None
        await complete_reset(async_db, handoff.reset_token, new_password)
        assert await async_db.get(ReadingSession, session_id) is not None

    await async_db.refresh(user)
    assert verify_password("third-password", user.password_hash)
    assert not verify_password("first-password", user.password_hash)


def test_auth_modules_do_not_import_reading_session_helpers() -> None:
    """Authentication code must not depend on reading-session persistence.

    Guards the original foot gun: an auth path calling a ``*_sessions_for_user``
    helper that silently operated on reading history.
    """
    violations: list[str] = []

    for rel in AUTH_MODULES:
        path = REPO_ROOT / rel
        assert path.exists(), f"expected auth module {rel} to exist"
        tree = ast.parse(path.read_text(), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported = [alias.name for alias in node.names]
                if "reading_session" in module or module.endswith("session_repository"):
                    violations.append(f"{rel}:{node.lineno} imports from {module}")
                for name in imported:
                    if "reading_session" in name:
                        violations.append(
                            f"{rel}:{node.lineno} imports reading-session symbol {name}"
                        )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "reading_session" in alias.name:
                        violations.append(f"{rel}:{node.lineno} imports {alias.name}")

    assert violations == [], (
        "Authentication modules must not import reading-session helpers:\n"
        + "\n".join(violations)
    )


def test_password_reset_source_contains_no_reading_session_deletion() -> None:
    """``password_reset_service`` must not delete rows from the sessions table."""
    source = (REPO_ROOT / "app/services/password_reset_service.py").read_text()
    for forbidden in (
        "delete_all_sessions_for_user",
        "delete_all_reading_sessions_for_user",
        "delete(ReadingSession",
        "delete(Session",
    ):
        assert forbidden not in source, (
            f"password reset must preserve reading history; found {forbidden!r}"
        )


def test_reading_session_repository_exposes_no_bulk_delete_helper() -> None:
    """No destructive bulk-delete helper remains on the reading-session repository.

    Criterion 2 of #2998 requires explicit reading-domain helper names; criterion 4
    requires auth code never to reach one. Deleting the ambiguous helper removes the
    class of mistake rather than only renaming it.
    """
    tree = ast.parse((REPO_ROOT / READING_SESSION_REPOSITORY_MODULE).read_text())
    destructive = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and ("delete_all" in node.name or node.name.startswith("delete_"))
    ]
    assert destructive == [], (
        "reading-session repository must not expose bulk-delete helpers: "
        f"{destructive}"
    )


def test_reading_session_model_is_not_exposed_as_bare_session() -> None:
    """``app.models`` must not re-export the reading-history model as ``Session``.

    Criterion 1 of #2998. A bare ``Session`` export is what let auth code read
    ``Session`` as if it were login state.
    """
    source = (REPO_ROOT / "app/models/__init__.py").read_text()
    tree = ast.parse(source)
    exported: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            continue
        value = node.value
        if not isinstance(value, ast.List):
            continue
        exported = [
            element.value
            for element in value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
    assert "ReadingSession" in exported
    assert "Session" not in exported


def test_ambiguous_legacy_session_module_paths_are_gone() -> None:
    """Reading-session modules must not keep their ambiguous ``session.py`` paths."""
    for rel in (
        "app/models/session.py",
        "app/schemas/session.py",
        "app/api/session.py",
        "app/repositories/session_repository.py",
    ):
        assert not (REPO_ROOT / rel).exists(), f"{rel} should have been renamed"


def test_application_code_never_aliases_the_reading_session_model_to_a_bare_session() -> None:
    """No module may re-introduce a bare ``Session``/``SessionModel`` alias for reading history.

    ``app.models`` no longer exports ``Session``, so an alias such as
    ``from app.models import ReadingSession as SessionModel`` is the only remaining way to smuggle
    the ambiguous name back into application code. Requiring the qualified alias keeps the
    reading/auth distinction visible at every call site.
    """
    violations: list[str] = []
    for path in sorted((REPO_ROOT / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                asname = alias.asname or ""
                if "Session" in asname and "ReadingSession" not in asname:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno} "
                        f"aliases {alias.name!r} as ambiguous {asname!r}"
                    )
    assert violations == [], (
        "reading-session imports must keep their qualified alias:\n" + "\n".join(violations)
    )