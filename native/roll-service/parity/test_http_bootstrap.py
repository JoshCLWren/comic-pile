"""Authenticated native Roll GET against isolated real Postgres tables, never production."""
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.models import Event, Issue, ReadingSession, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping, ThreadExternalSeriesMapping
from app.models.tag import Tag, TagAssignment

SECRET = "synthetic-native-http-secret"


@pytest.mark.asyncio
async def test_authenticated_roll_v2_http_returns_real_owned_session_and_mapped_candidate():
    """Exercise the mounted GET, its session writes, eligibility SQL and output fields."""
    url = os.environ.get("RUST_ROLL_TEST_DATABASE_URL")
    if url is None:
        pytest.skip(
            "disposable test Postgres (RUST_ROLL_TEST_DATABASE_URL) is not available"
        )
    name = f"rust_http_{uuid4().hex}"
    admin = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{name}"'))
    engine = create_async_engine(
        url.replace("postgresql://", "postgresql+asyncpg://"),
        connect_args={"server_settings": {"search_path": name}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        now = datetime.now(UTC)
        username = f"nr_{uuid4().hex[:16]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            stranger = User(username=f"other_{uuid4().hex[:16]}")
            db.add_all([owner, stranger])
            await db.flush()
            t = Thread(user_id=owner.id, title="Known Series", format="Comic",
                       queue_position=1, issues_remaining=1, total_issues=2,
                       # Deliberately stale persisted flag: live Option E says readable.
                       is_blocked=True, last_activity_at=now-timedelta(days=8))
            stale_other = Thread(user_id=owner.id, title="Other stale series", format="Comic",
                                 queue_position=2, issues_remaining=1,
                                 last_activity_at=now-timedelta(days=9))
            stale_snoozed = Thread(user_id=owner.id, title="Snoozed stale series", format="Comic",
                                   queue_position=3, issues_remaining=1,
                                   last_activity_at=now-timedelta(days=10))
            stale_skipped = Thread(user_id=owner.id, title="Skipped stale series", format="Comic",
                                   queue_position=4, issues_remaining=1,
                                   last_activity_at=now-timedelta(days=10))
            completed = Thread(user_id=owner.id, title="Read completely", format="Comic",
                               status="completed", queue_position=0, issues_remaining=0)
            unqueued = Thread(user_id=owner.id, title="Not in queue", format="Comic",
                              status="active", queue_position=0, issues_remaining=1)
            foreign = Thread(user_id=stranger.id, title="Private",
                             format="Comic", queue_position=1, issues_remaining=1,
                             last_activity_at=now-timedelta(days=10))
            db.add_all([t, foreign, stale_other, stale_snoozed, stale_skipped,
                        completed, unqueued])
            await db.flush()
            read = Issue(thread_id=t.id, issue_number="1", position=1,
                         status="read", read_at=now-timedelta(minutes=10))
            next_issue = Issue(thread_id=t.id, issue_number="2", position=2, status="unread")
            foreign_issue = Issue(thread_id=foreign.id, issue_number="1",
                                  position=1, status="unread")
            completed_issue = Issue(thread_id=completed.id, issue_number="1",
                                    position=1, status="read", read_at=now)
            unqueued_issue = Issue(thread_id=unqueued.id, issue_number="1",
                                   position=1, status="unread")
            db.add_all([read, next_issue, foreign_issue, completed_issue, unqueued_issue])
            for stale in (stale_other, stale_snoozed, stale_skipped):
                db.add(Issue(thread_id=stale.id, issue_number="1", position=1, status="unread"))
            await db.flush()
            t.next_unread_issue_id = next_issue.id
            external = ExternalIdentity(
                provider="comicvine", entity_type="issue", external_id="4000-567",
                metadata_json={"volume": {"id": 123, "name": "Known Series"},
                               "image_url": "https://example.com/cover.jpg"},
            )
            series = ExternalIdentity(
                provider="comicvine", entity_type="series", external_id="123",
                metadata_json={"name": "Known Series", "count_of_issues": 15},
            )
            db.add_all([external, series])
            await db.flush()
            db.add_all([
                IssueExternalIdentityMapping(issue_id=next_issue.id,
                                             external_identity_id=external.id,status="confirmed"),
                IssueExternalIdentityMapping(issue_id=read.id,
                                             external_identity_id=external.id,status="confirmed"),
                ThreadExternalSeriesMapping(thread_id=t.id,
                                            external_identity_id=series.id,status="confirmed"),
            ])
            tag = Tag(name="Favorites",normalized_name="favorites",scope="global",
                      color="#336699",owner_user_id=None)
            db.add(tag)
            await db.flush()
            db.add(TagAssignment(tag_id=tag.id,target_type="Thread",target_id=t.id))
            session = ReadingSession(
                user_id=owner.id,started_at=now-timedelta(minutes=3),
                start_die=6,pending_thread_id=t.id,pending_issue_id=next_issue.id,
                pending_thread_updated_at=now-timedelta(minutes=2),
                bandwidth_source="manual",active_bandwidth="balanced",
                predicted_bandwidth="light",
                snoozed_thread_ids=[stale_snoozed.id], skipped_thread_ids=[stale_skipped.id],
            )
            db.add(session)
            await db.flush()
            db.add_all([
                Event(session_id=session.id,thread_id=t.id,issue_id=read.id,
                      type="rate",rating=4.5,timestamp=now-timedelta(minutes=1)),
                Event(session_id=session.id,thread_id=t.id,selected_thread_id=t.id,
                      issue_id=next_issue.id,type="roll",result=3,timestamp=now),
            ])
            owner_id = owner.id
            next_id = next_issue.id
            foreign_id = foreign.id
            completed_id = completed.id
            unqueued_id = unqueued.id
            await db.commit()

        token = jwt.encode({"sub":username,"jti":"native-http-fixture",
                            "type":"access","exp":int((now+timedelta(hours=1)).timestamp())},
                           SECRET,"HS256")
        query = f"options=-csearch_path%3D{name}"
        env = {**os.environ,
               "RUST_ROLL_DATABASE_URL":url+("&" if "?" in url else "?")+query,
               "RUST_ROLL_JWT_SECRET":SECRET,
               "RUST_ROLL_TEST_TOKEN":token,
               "RUST_ROLL_POOL_SIZE":"2"}
        proc = await asyncio.create_subprocess_exec(
            "native/roll-service/target/debug/examples/http_bootstrap",
            env=env,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(),25)
        assert proc.returncode == 0,err.decode()
        result = json.loads(out)
        assert result["status"] == 200, result
        body = result["body"]
        assert body["session_id"] == session.id
        assert body["user_id"] == owner_id
        assert body["pending_thread_id"] == t.id
        assert body["active_thread"]["id"] == t.id
        assert body["active_thread"]["tags"][0]["name"] == "Favorites"
        assert body["last_rolled_result"] == 3
        assert body["timezone"] == "America/Chicago"
        assert len(body["rollable"]) == 2
        assert body["stale_thread_count"] == 2
        assert body["stale_thread"]["id"] in {t.id, stale_other.id}
        assert body["stale_thread"]["id"] not in {foreign_id, stale_snoozed.id, stale_skipped.id}
        candidate = body["rollable"][0]
        assert candidate["thread"]["id"] == t.id
        assert candidate["thread"]["tags"][0]["name"] == "Favorites"
        # Four excluded series: snoozed, skipped, completed, and unqueued.
        # The completed/unqueued rows prevent hidden-inactive regressions.
        assert body["total_threads"] == 6
        assert body["available_threads"] == 2
        assert body["excluded_count"] == 4
        assert body["inactive_count"] == 2
        assert {
            row["thread_id"]: row["reason"] for row in body["inactive_threads"]
        } == {completed_id: "completed", unqueued_id: "not_in_queue"}
        assert {
            row["thread_id"]: row["reason"] for row in body["excluded_threads"]
        } == {
            completed_id: "completed",
            unqueued_id: "not_in_queue",
            stale_snoozed.id: "snoozed",
            stale_skipped.id: "skipped",
        }
        assert {row["thread"]["id"] for row in body["rollable"]}.isdisjoint(
            {completed_id, unqueued_id, foreign_id}
        )
        assert t.id not in {row["id"] for row in body["blocked_threads"]}
        assert t.id not in {row["thread_id"] for row in body["excluded_threads"]}
        assert candidate["thread"]["id"] != foreign_id
        assert candidate["issue"]["id"] == next_id
        assert candidate["issue"]["cover_url"] == "https://example.com/cover.jpg"
        assert candidate["identity"]["canonical_series_id"] == "123"
        assert candidate["reader"]["progress_scope"] == "canonical_series_run"
        assert candidate["reader"]["read_count"] == 1
        assert candidate["reader"]["rating_count"] == 1
        assert candidate["reader"]["average_rating"] == 4.5
        assert candidate["reader"]["issue_count"] == 15
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        await admin.dispose()
