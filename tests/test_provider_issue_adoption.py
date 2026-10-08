"""Contract tests for provider issue adoption into an owned thread (#3114)."""

from dataclasses import dataclass

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.comicvine_hydration import COMICVINE_PROVIDER
from app.external_identities import link_issue_external_identity, upsert_external_identity
from app.models import Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.services.provider_issue_adoption import adopt_comicvine_issue
from comic_pile.comicvine_provider import ComicVineClient, ComicVineError, ComicVineResponse


async def _owned_thread(
    db: AsyncSession,
    *,
    username: str,
    title: str,
    status: str = "active",
) -> tuple[User, Thread]:
    user = User(username=username)
    db.add(user)
    await db.flush()
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status=status,
        user_id=user.id,
    )
    db.add(thread)
    await db.flush()
    return user, thread


@dataclass
class _FakeComicVineClient(ComicVineClient):
    payload: dict[str, object] | None = None
    error: Exception | None = None

    def __init__(self, payload: dict[str, object] | None = None, error: Exception | None = None):
        self.payload = payload
        self.error = error

    async def fetch_issue(self, issue_id: int, *, refresh: bool = False) -> ComicVineResponse:
        if self.error is not None:
            raise self.error
        assert self.payload is not None
        return ComicVineResponse(payload=self.payload, from_cache=False, cache_key="fake")

    async def fetch_story_arc(self, arc_id: int, *, refresh: bool = False) -> ComicVineResponse:
        raise ComicVineError("no story arcs in fake client")


def _issue_payload(comicvine_issue_id: int, issue_number: str) -> dict[str, object]:
    return {
        "results": {
            "id": comicvine_issue_id,
            "issue_number": issue_number,
            "name": f"Issue {issue_number}",
            "site_detail_url": f"https://comicvine.gamespot.com/issue/4000-{comicvine_issue_id}/",
        }
    }


async def _issue_count(db: AsyncSession, thread_id: int) -> int:
    return await db.scalar(
        select(func.count()).select_from(Issue).where(Issue.thread_id == thread_id)
    ) or 0


@pytest.mark.asyncio
async def test_adoption_creates_issue_and_confirms_identity(async_db: AsyncSession) -> None:
    """A new provider issue appends a canonical Issue with a confirmed mapping."""
    user, thread = await _owned_thread(
        async_db, username="adopt_create", title="Saga"
    )
    result = await adopt_comicvine_issue(
        async_db,
        user_id=user.id,
        thread_id=thread.id,
        comicvine_issue_id=400001,
        issue_number="1",
    )

    assert result.outcome == "created"
    assert result.issue_id is not None
    assert result.hydration == "not_attempted"

    issue = await async_db.get(Issue, result.issue_id)
    assert issue is not None
    assert issue.thread_id == thread.id
    assert issue.issue_number == "1"
    assert issue.status == "unread"

    mapping = await async_db.scalar(
        select(IssueExternalIdentityMapping).where(
            IssueExternalIdentityMapping.issue_id == issue.id
        )
    )
    assert mapping is not None
    assert mapping.status == "confirmed"
    identity = await async_db.get(ExternalIdentity, mapping.external_identity_id)
    assert identity is not None
    assert identity.provider == COMICVINE_PROVIDER
    assert identity.entity_type == "issue"
    assert identity.external_id == "400001"

    await async_db.refresh(thread)
    assert thread.total_issues == 1
    assert thread.issues_remaining == 1
    assert thread.next_unread_issue_id == issue.id


@pytest.mark.asyncio
async def test_adoption_retry_is_idempotent(async_db: AsyncSession) -> None:
    """Retrying with the same ComicVine issue ID never duplicates the Issue."""
    user, thread = await _owned_thread(
        async_db, username="adopt_retry", title="Saga"
    )
    first = await adopt_comicvine_issue(
        async_db,
        user_id=user.id,
        thread_id=thread.id,
        comicvine_issue_id=400002,
        issue_number="2",
    )
    second = await adopt_comicvine_issue(
        async_db,
        user_id=user.id,
        thread_id=thread.id,
        comicvine_issue_id=400002,
        issue_number="2",
    )

    assert first.outcome == "created"
    assert second.outcome == "reused"
    assert second.issue_id == first.issue_id
    assert await _issue_count(async_db, thread.id) == 1


@pytest.mark.asyncio
async def test_adoption_reuses_existing_canonical_mapping(async_db: AsyncSession) -> None:
    """An already confirmed mapping is reused even on a thread with other issues."""
    user, thread = await _owned_thread(
        async_db, username="adopt_reuse", title="Saga"
    )
    issue = Issue(thread_id=thread.id, issue_number="3", position=1, status="read")
    async_db.add(issue)
    await async_db.flush()
    identity = await upsert_external_identity(
        async_db, provider=COMICVINE_PROVIDER, entity_type="issue", external_id="400003"
    )
    await link_issue_external_identity(
        async_db,
        user_id=user.id,
        issue_id=issue.id,
        external_identity_id=identity.id,
        status="confirmed",
    )

    result = await adopt_comicvine_issue(
        async_db,
        user_id=user.id,
        thread_id=thread.id,
        comicvine_issue_id=400003,
        issue_number="3",
    )

    assert result.outcome == "reused"
    assert result.issue_id == issue.id
    assert await _issue_count(async_db, thread.id) == 1
    # Existing read state is preserved.
    await async_db.refresh(issue)
    assert issue.status == "read"


@pytest.mark.asyncio
async def test_adoption_conflict_with_confirmed_identity_on_other_thread(
    async_db: AsyncSession,
) -> None:
    """A ComicVine identity already confirmed on another thread fails closed."""
    user, thread = await _owned_thread(
        async_db, username="adopt_conflict_thread", title="Saga"
    )
    other_thread = Thread(
        title="Other",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add(other_thread)
    await async_db.flush()
    other_issue = Issue(thread_id=other_thread.id, issue_number="1", position=1)
    async_db.add(other_issue)
    await async_db.flush()
    identity = await upsert_external_identity(
        async_db, provider=COMICVINE_PROVIDER, entity_type="issue", external_id="400004"
    )
    await link_issue_external_identity(
        async_db,
        user_id=user.id,
        issue_id=other_issue.id,
        external_identity_id=identity.id,
        status="confirmed",
    )

    result = await adopt_comicvine_issue(
        async_db,
        user_id=user.id,
        thread_id=thread.id,
        comicvine_issue_id=400004,
        issue_number="1",
    )

    assert result.outcome == "conflict"
    assert result.issue_id == other_issue.id
    assert result.conflict_detail
    assert await _issue_count(async_db, thread.id) == 0
    # The conflicting mapping is untouched.
    mapping = await async_db.scalar(
        select(IssueExternalIdentityMapping).where(
            IssueExternalIdentityMapping.issue_id == other_issue.id
        )
    )
    assert mapping is not None
    assert mapping.status == "confirmed"
    assert mapping.external_identity_id == identity.id


@pytest.mark.asyncio
async def test_adoption_conflict_when_local_issue_has_other_confirmed_identity(
    async_db: AsyncSession,
) -> None:
    """A local issue already confirmed to a different ComicVine ID fails closed."""
    user, thread = await _owned_thread(
        async_db, username="adopt_conflict_identity", title="Saga"
    )
    issue = Issue(thread_id=thread.id, issue_number="5", position=1)
    async_db.add(issue)
    await async_db.flush()
    existing_identity = await upsert_external_identity(
        async_db, provider=COMICVINE_PROVIDER, entity_type="issue", external_id="400005"
    )
    existing_mapping = await link_issue_external_identity(
        async_db,
        user_id=user.id,
        issue_id=issue.id,
        external_identity_id=existing_identity.id,
        status="confirmed",
    )

    result = await adopt_comicvine_issue(
        async_db,
        user_id=user.id,
        thread_id=thread.id,
        comicvine_issue_id=400006,
        issue_number="5",
    )

    assert result.outcome == "conflict"
    assert result.issue_id == issue.id
    await async_db.refresh(existing_mapping)
    assert existing_mapping.external_identity_id == existing_identity.id
    # No orphan mapping to the incoming identity was persisted.
    incoming = await async_db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == COMICVINE_PROVIDER,
            ExternalIdentity.entity_type == "issue",
            ExternalIdentity.external_id == "400006",
        )
    )
    if incoming is not None:
        orphan = await async_db.scalar(
            select(IssueExternalIdentityMapping).where(
                IssueExternalIdentityMapping.external_identity_id == incoming.id
            )
        )
        assert orphan is None


@pytest.mark.asyncio
async def test_adoption_preserves_irregular_issue_number_verbatim(
    async_db: AsyncSession,
) -> None:
    """Annual/fractional/named numbering is stored exactly as ComicVine reports it."""
    user, thread = await _owned_thread(
        async_db, username="adopt_irregular", title="Annuals"
    )
    for comicvine_issue_id, number in ((400007, "Annual 1"), (400008, "1.5"), (400009, "½")):
        result = await adopt_comicvine_issue(
            async_db,
            user_id=user.id,
            thread_id=thread.id,
            comicvine_issue_id=comicvine_issue_id,
            issue_number=number,
        )
        assert result.outcome == "created"

    numbers = [
        row[0]
        for row in (
            await async_db.execute(
                select(Issue.issue_number)
                .where(Issue.thread_id == thread.id)
                .order_by(Issue.position)
            )
        ).all()
    ]
    assert numbers == ["Annual 1", "1.5", "½"]


@pytest.mark.asyncio
async def test_adoption_reopens_completed_thread(async_db: AsyncSession) -> None:
    """Adding an unread issue recalculates tracking and reactivates a completed thread."""
    user, thread = await _owned_thread(
        async_db, username="adopt_reopen", title="Done Series", status="completed"
    )
    read_issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="read")
    async_db.add(read_issue)
    await async_db.flush()
    thread.total_issues = 1
    thread.issues_remaining = 0
    thread.next_unread_issue_id = None
    thread.reading_progress = "completed"
    await async_db.flush()

    result = await adopt_comicvine_issue(
        async_db,
        user_id=user.id,
        thread_id=thread.id,
        comicvine_issue_id=400010,
        issue_number="2",
    )

    assert result.outcome == "created"
    await async_db.refresh(thread)
    assert thread.status == "active"
    assert thread.queue_position == 1
    assert thread.total_issues == 2
    assert thread.issues_remaining == 1
    assert thread.next_unread_issue_id == result.issue_id
    assert thread.reading_progress == "in_progress"


@pytest.mark.asyncio
async def test_adoption_natural_order_reseats_positions(async_db: AsyncSession) -> None:
    """An ordinary number adopts at its natural position, shifting later issues."""
    user, thread = await _owned_thread(
        async_db, username="adopt_natural", title="Numbered"
    )
    for position, number in enumerate(("33", "34", "35"), start=1):
        async_db.add(
            Issue(thread_id=thread.id, issue_number=number, position=position, status="read")
        )
    await async_db.flush()

    result = await adopt_comicvine_issue(
        async_db,
        user_id=user.id,
        thread_id=thread.id,
        comicvine_issue_id=400011,
        issue_number="2",
    )

    assert result.outcome == "created"
    ordered = (
        await async_db.execute(
            select(Issue.issue_number, Issue.position)
            .where(Issue.thread_id == thread.id)
            .order_by(Issue.position)
        )
    ).all()
    assert [(row[0], row[1]) for row in ordered] == [
        ("2", 1),
        ("33", 2),
        ("34", 3),
        ("35", 4),
    ]
    # Reseating only touches position; read state is preserved.
    statuses = (
        await async_db.execute(
            select(Issue.status).where(Issue.thread_id == thread.id).order_by(Issue.position)
        )
    ).scalars().all()
    assert list(statuses) == ["unread", "read", "read", "read"]


@pytest.mark.asyncio
async def test_adoption_hydration_failure_does_not_duplicate_on_retry(
    async_db: AsyncSession,
) -> None:
    """A hydration failure after safe local creation is recoverable on retry."""
    user, thread = await _owned_thread(
        async_db, username="adopt_hydration", title="Hydration"
    )
    failing_client = _FakeComicVineClient(error=ComicVineError("provider down"))

    first = await adopt_comicvine_issue(
        async_db,
        user_id=user.id,
        thread_id=thread.id,
        comicvine_issue_id=400012,
        issue_number="7",
        comicvine_client=failing_client,
    )
    assert first.outcome == "created"
    assert first.hydration == "failed"

    healthy_client = _FakeComicVineClient(payload=_issue_payload(400012, "7"))
    second = await adopt_comicvine_issue(
        async_db,
        user_id=user.id,
        thread_id=thread.id,
        comicvine_issue_id=400012,
        issue_number="7",
        comicvine_client=healthy_client,
    )
    assert second.outcome == "reused"
    assert second.issue_id == first.issue_id
    assert second.hydration == "hydrated"
    assert await _issue_count(async_db, thread.id) == 1

    identity = await async_db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == COMICVINE_PROVIDER,
            ExternalIdentity.entity_type == "issue",
            ExternalIdentity.external_id == "400012",
        )
    )
    assert identity is not None
    assert identity.metadata_json.get("name") == "Issue 7"


@pytest.mark.asyncio
async def test_adoption_hydrates_metadata_on_create(async_db: AsyncSession) -> None:
    """Successful adoption hydrates provider metadata through the hydration boundary."""
    user, thread = await _owned_thread(
        async_db, username="adopt_hydrate_ok", title="Hydrated"
    )
    client = _FakeComicVineClient(payload=_issue_payload(400013, "9"))
    result = await adopt_comicvine_issue(
        async_db,
        user_id=user.id,
        thread_id=thread.id,
        comicvine_issue_id=400013,
        issue_number="9",
        comicvine_client=client,
    )

    assert result.outcome == "created"
    assert result.hydration == "hydrated"
    identity = await async_db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == COMICVINE_PROVIDER,
            ExternalIdentity.entity_type == "issue",
            ExternalIdentity.external_id == "400013",
        )
    )
    assert identity is not None
    assert identity.metadata_json.get("issue_number") == "9"


@pytest.mark.asyncio
async def test_adoption_requires_owned_thread(async_db: AsyncSession) -> None:
    """Adoption into a thread owned by someone else is rejected."""
    _owner, thread = await _owned_thread(
        async_db, username="adopt_owner", title="Mine"
    )
    stranger = User(username="adopt_stranger")
    async_db.add(stranger)
    await async_db.flush()

    with pytest.raises(HTTPException):
        await adopt_comicvine_issue(
            async_db,
            user_id=stranger.id,
            thread_id=thread.id,
            comicvine_issue_id=400014,
            issue_number="1",
        )
    assert await _issue_count(async_db, thread.id) == 0
