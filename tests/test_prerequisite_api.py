"""Stable prerequisites preserve intent across duplicate writes and list edits."""

import pytest
from sqlalchemy import select

from app.models import Dependency, Issue, Thread, User
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList


@pytest.fixture
async def prerequisite_issues(async_db, test_username, auth_client):
    """Create independently progressing series for the authenticated reader."""
    user = (await async_db.scalars(select(User).where(User.username == test_username))).one()
    issues = []
    for position in range(3):
        thread = Thread(
            title=f"Prerequisite {position}",
            format="Comic",
            user_id=user.id,
            status="active",
            queue_position=position + 1,
            issues_remaining=1,
        )
        async_db.add(thread)
        await async_db.flush()
        issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
        async_db.add(issue)
        await async_db.flush()
        issues.append(issue)
    await async_db.commit()
    return issues


async def test_idempotent_fanout_survives_list_delete(
    auth_client, async_db, prerequisite_issues, test_username
):
    """One source can require two targets; lists never own stable requirements."""
    user = (await async_db.scalars(select(User).where(User.username == test_username))).one()
    source, first, second = prerequisite_issues
    ids = []
    for target in (first, second):
        payload = {"source_issue_id": source.id, "target_issue_id": target.id}
        response = await auth_client.post("/api/v1/prerequisites/", json=payload)
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["origin"] == "reader"
        assert result["classification"] == "A"
        ids.append(result["id"])
        duplicate = await auth_client.post("/api/v1/prerequisites/", json=payload)
        assert duplicate.json()["id"] == result["id"]
    reading_list = CustomCBLList(user_id=user.id, name="Shared placement")
    async_db.add(reading_list)
    await async_db.flush()
    async_db.add_all(
        [
            CustomCBLEntry(list_id=reading_list.id, issue_id=issue.id, position=p)
            for p, issue in enumerate((source, first, second))
        ]
    )
    await async_db.commit()
    await async_db.delete(reading_list)
    await async_db.commit()
    response = await auth_client.get("/api/v1/prerequisites/")
    assert {row["id"] for row in response.json()} == set(ids)
    for issue in prerequisite_issues:
        await async_db.refresh(issue)
        assert issue.status == "unread"
    edited = await auth_client.patch(f"/api/v1/prerequisites/{ids[0]}", json={"note": "Read first"})
    assert edited.status_code == 200
    assert edited.json()["source_issue_id"] == source.id
    assert edited.json()["note"] == "Read first"
    deleted = await auth_client.delete(f"/api/v1/prerequisites/{ids[0]}")
    assert deleted.status_code == 204
    assert len((await auth_client.get("/api/v1/prerequisites/")).json()) == 1


async def test_historical_unknown_is_not_reader_approval(
    auth_client, async_db, prerequisite_issues
):
    """Duplicate creation cannot overwrite legacy provenance or allow retirement."""
    source, target, _ = prerequisite_issues
    row = Dependency(source_issue_id=source.id, target_issue_id=target.id, note="legacy evidence")
    async_db.add(row)
    await async_db.commit()
    row_id = row.id
    result = await auth_client.post(
        "/api/v1/prerequisites/",
        json={"source_issue_id": source.id, "target_issue_id": target.id, "note": "replacement"},
    )
    assert result.status_code == 201
    assert result.json()["origin"] is None
    assert result.json()["classification"] is None
    assert result.json()["note"] == "legacy evidence"
    for response in (
        await auth_client.patch(f"/api/v1/prerequisites/{row_id}", json={"note": "changed"}),
        await auth_client.delete(f"/api/v1/prerequisites/{row_id}"),
    ):
        assert response.status_code == 409
    await async_db.refresh(row)
    assert row.note == "legacy evidence"


async def test_invalid_pairs_and_cycles_fail_closed(auth_client, async_db, prerequisite_issues):
    """Reject self, dangling, foreign and transitive cyclic requirements."""
    a, b, c = prerequisite_issues
    foreign = User(username="foreign_prerequisite", password_hash="unused")
    async_db.add(foreign)
    await async_db.flush()
    thread = Thread(
        title="Foreign",
        user_id=foreign.id,
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.commit()
    for source_id, target_id, expected in (
        (a.id, a.id, 422),
        (a.id, 99999999, 404),
        (a.id, issue.id, 404),
        (issue.id, a.id, 404),
        (a.id, b.id, 201),
        (b.id, c.id, 201),
        (c.id, a.id, 422),
    ):
        response = await auth_client.post(
            "/api/v1/prerequisites/",
            json={
                "source_issue_id": source_id,
                "target_issue_id": target_id,
            },
        )
        assert response.status_code == expected, response.text
    rows = list((await async_db.scalars(select(Dependency))).all())
    assert len(rows) == 2


async def test_cycle_includes_strict_list_and_read_issues(
    auth_client, async_db, prerequisite_issues, test_username
):
    """Read state does not permit a prerequisite to reverse strict list order."""
    source, target, _ = prerequisite_issues
    user = (await async_db.scalars(select(User).where(User.username == test_username))).one()
    reading_list = CustomCBLList(user_id=user.id, name="Strict order", mode="strict")
    async_db.add(reading_list)
    await async_db.flush()
    async_db.add_all(
        [
            CustomCBLEntry(list_id=reading_list.id, issue_id=source.id, position=0),
            CustomCBLEntry(list_id=reading_list.id, issue_id=target.id, position=1),
        ]
    )
    source.status = "read"
    target.status = "read"
    await async_db.commit()
    response = await auth_client.post(
        "/api/v1/prerequisites/",
        json={
            "source_issue_id": target.id,
            "target_issue_id": source.id,
        },
    )
    assert response.status_code == 422
    assert "Strict order" in response.text
    assert "prerequisite" in response.text
    assert not list((await async_db.scalars(select(Dependency))).all())


async def test_converted_provenance_is_read_only(auth_client, async_db, prerequisite_issues):
    """Converted unknown evidence stays visible and cannot be silently approved."""
    source, target, _ = prerequisite_issues
    row = Dependency(
        source_issue_id=source.id,
        target_issue_id=target.id,
        origin="converted",
        classification="D",
        provenance="archive dependency 44; intent unknown",
        note="original source",
    )
    async_db.add(row)
    await async_db.commit()
    result = (await auth_client.get("/api/v1/prerequisites/")).json()[0]
    assert result["classification"] == "D"
    assert result["provenance"] == "archive dependency 44; intent unknown"
    response = await auth_client.delete(f"/api/v1/prerequisites/{row.id}")
    assert response.status_code == 409
    forged = await auth_client.post(
        "/api/v1/prerequisites/",
        json={
            "source_issue_id": source.id,
            "target_issue_id": target.id,
            "origin": "reader",
        },
    )
    assert forged.status_code == 422
