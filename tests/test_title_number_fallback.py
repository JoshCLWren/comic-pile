"""Title + issue number fallback for CBL entries with no owned ComicVine mapping.

An owner may hold the physical comic without a ComicVine mapping. When a CBL
entry's ComicVine ID has no owned mapping, resolution falls back to an exact
normalized title + issue number match before declaring the entry missing, so
adoption reuses the owned comic instead of creating a duplicate.
"""

from __future__ import annotations


import pytest
from sqlalchemy import func, select

from app.external_identities import link_issue_external_identity, upsert_external_identity
from app.models.issue import Issue
from app.models.thread import Thread
from app.models.user import User
from app.services.issue_identity_reconciliation import (
    resolve_cbl_entries_to_canonical,
)


async def _user(async_db, username: str) -> User:
    result = await async_db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(username=username)
        async_db.add(user)
        await async_db.flush()
        await async_db.refresh(user)
    return user


async def _thread(async_db, user_id: int, title: str) -> Thread:
    max_pos = (
        await async_db.execute(select(func.max(Thread.queue_position)).where(Thread.user_id == user_id))
    ).scalar() or 0
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=0,
        queue_position=max_pos + 1,
        status="active",
        user_id=user_id,
    )
    async_db.add(thread)
    await async_db.flush()
    await async_db.refresh(thread)
    return thread


async def _issues(async_db, thread_id: int, numbers: list[str]) -> list[Issue]:
    created: list[Issue] = []
    for idx, num in enumerate(numbers, start=1):
        issue = Issue(
            thread_id=thread_id,
            issue_number=num,
            position=idx,
            status="unread",
            read_at=None,
        )
        async_db.add(issue)
        await async_db.flush()
        await async_db.refresh(issue)
        created.append(issue)
    return created


async def _comicvine_identity(async_db, external_id: str) -> None:
    """Create the ComicVine identity row without linking it to any owned issue."""
    await upsert_external_identity(
        async_db, provider="comicvine", entity_type="issue", external_id=external_id
    )
    await async_db.flush()


@pytest.mark.asyncio
async def test_fallback_reuses_unmapped_owned_issue(async_db) -> None:
    """A single exact title+number match is reused, not declared missing."""
    user = await _user(async_db, username="fallback_user")
    thread = await _thread(async_db, user.id, "My Series")
    issues = await _issues(async_db, thread.id, ["1"])
    await _comicvine_identity(async_db, "99999")

    entries = [
        {"position": 1, "series_name": "My Series", "issue_number": "1", "comicvine_issue_id": "99999"},
    ]
    resolved = await resolve_cbl_entries_to_canonical(async_db, user_id=user.id, cbl_entries=entries)
    assert resolved[0].resolution_status == "resolved_via_title_number_fallback"
    assert resolved[0].resolved_issue_id == issues[0].id
    assert resolved[0].canonical_issue_id == issues[0].id


@pytest.mark.asyncio
async def test_fallback_normalizes_case_and_whitespace(async_db) -> None:
    """Matching tolerates case differences and collapsed whitespace."""
    user = await _user(async_db, username="fallback_norm_user")
    thread = await _thread(async_db, user.id, "My  Series")
    issues = await _issues(async_db, thread.id, [" 2 "])
    await _comicvine_identity(async_db, "99998")

    entries = [
        {"position": 1, "series_name": "my series", "issue_number": "2", "comicvine_issue_id": "99998"},
    ]
    resolved = await resolve_cbl_entries_to_canonical(async_db, user_id=user.id, cbl_entries=entries)
    assert resolved[0].resolution_status == "resolved_via_title_number_fallback"
    assert resolved[0].resolved_issue_id == issues[0].id


@pytest.mark.asyncio
async def test_fallback_multiple_matches_are_ambiguous(async_db) -> None:
    """Multiple title+number matches are surfaced, never auto-merged."""
    user = await _user(async_db, username="fallback_multi_user")
    thread_a = await _thread(async_db, user.id, "Dup Series")
    thread_b = await _thread(async_db, user.id, "dup  series")
    await _issues(async_db, thread_a.id, ["1"])
    await _issues(async_db, thread_b.id, ["1"])
    await _comicvine_identity(async_db, "99997")

    entries = [
        {"position": 1, "series_name": "Dup Series", "issue_number": "1", "comicvine_issue_id": "99997"},
    ]
    resolved = await resolve_cbl_entries_to_canonical(async_db, user_id=user.id, cbl_entries=entries)
    assert resolved[0].resolution_status == "ambiguous_title_number_multiple_matches"
    assert resolved[0].resolved_issue_id is None


@pytest.mark.asyncio
async def test_fallback_no_match_stays_missing(async_db) -> None:
    """No title+number match keeps the entry missing (importable)."""
    user = await _user(async_db, username="fallback_missing_user")
    thread = await _thread(async_db, user.id, "Other Series")
    await _issues(async_db, thread.id, ["1"])
    await _comicvine_identity(async_db, "99996")

    entries = [
        {"position": 1, "series_name": "My Series", "issue_number": "1", "comicvine_issue_id": "99996"},
    ]
    resolved = await resolve_cbl_entries_to_canonical(async_db, user_id=user.id, cbl_entries=entries)
    assert resolved[0].resolution_status == "no_owned_issue_for_comicvine_id"
    assert resolved[0].resolved_issue_id is None


@pytest.mark.asyncio
async def test_fallback_does_not_override_comicvine_evidence(async_db) -> None:
    """ComicVine-mapped entries still resolve via ComicVine, not the fallback."""
    user = await _user(async_db, username="fallback_cv_user")
    thread = await _thread(async_db, user.id, "CV Series")
    issues = await _issues(async_db, thread.id, ["1"])
    identity = await upsert_external_identity(
        async_db, provider="comicvine", entity_type="issue", external_id="55555"
    )
    await link_issue_external_identity(
        async_db,
        user_id=user.id,
        issue_id=issues[0].id,
        external_identity_id=identity.id,
        status="confirmed",
        evidence_source="test",
        confidence=1.0,
    )
    await async_db.flush()

    entries = [
        {"position": 1, "series_name": "CV Series", "issue_number": "1", "comicvine_issue_id": "55555"},
    ]
    resolved = await resolve_cbl_entries_to_canonical(async_db, user_id=user.id, cbl_entries=entries)
    assert resolved[0].resolution_status == "resolved_via_comicvine_canonical"
    assert resolved[0].resolved_issue_id == issues[0].id


@pytest.mark.asyncio
async def test_fallback_scoped_to_owner(async_db) -> None:
    """The fallback never matches another user's comics."""
    owner = await _user(async_db, username="fallback_owner_user")
    other = await _user(async_db, username="fallback_other_user")
    thread = await _thread(async_db, other.id, "Shared Series")
    await _issues(async_db, thread.id, ["1"])
    await _comicvine_identity(async_db, "99995")

    entries = [
        {"position": 1, "series_name": "Shared Series", "issue_number": "1", "comicvine_issue_id": "99995"},
    ]
    resolved = await resolve_cbl_entries_to_canonical(async_db, user_id=owner.id, cbl_entries=entries)
    assert resolved[0].resolution_status == "no_owned_issue_for_comicvine_id"
    assert resolved[0].resolved_issue_id is None
