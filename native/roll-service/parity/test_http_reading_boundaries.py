"""Authenticated native reading-boundaries POST against the real app schema.

The synthetic schema is created from the canonical SQLAlchemy models, so the
handler runs against the same tables production migrations create. The expected
payload comes from the canonical Python service on that same data, then the
mounted Rust route must return it byte-for-byte.
"""
import asyncio
import json
import os
import resource
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_reading_execution_settings
from app.database import Base
from app.models import Dependency, Issue, Thread, User
from app.models.custom_cbl import (
    CustomCBLEntry,
    CustomCBLList,
    CustomCBLOverlapDecision,
)
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.schemas.reading_boundary import ReadingBoundaryExplanationV2
from app.services.reading_boundary_service import get_reading_boundary_explanations

SECRET = "synthetic-native-reading-boundary-secret"


async def _run_example(env: dict[str, str]) -> tuple[dict[str, object], bytes, float, float]:
    """Run the mounted Rust route and return body, bytes, wall, and child CPU."""
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    proc = await asyncio.create_subprocess_exec(
        "native/roll-service/target/debug/examples/http_reading_boundaries",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), 25)
    wall = time.perf_counter() - started
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    assert proc.returncode == 0, err.decode()
    return json.loads(out), out, wall, cpu


async def _db_bytes(admin) -> tuple[int, int]:
    async with admin.connect() as connection:
        row = await connection.execute(
            text(
                "SELECT xact_commit + xact_rollback, blks_read + blks_hit "
                "FROM pg_stat_database WHERE datname = current_database()"
            )
        )
        return tuple(int(value) for value in row.one())


@pytest.mark.asyncio
async def test_authenticated_reading_boundaries_v2_matches_canonical_service(
    monkeypatch: pytest.MonkeyPatch,
):
    """Exercise strict/loose, hold, prerequisite, multi-list, unmapped and cross-user."""
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv(
        "OPTION_E_APPROVED_PREVIEW", "native-parity-fixture-no-production-approval"
    )
    get_reading_execution_settings.cache_clear()

    url = os.environ["RUST_ROLL_TEST_DATABASE_URL"]
    name = f"rust_boundary_{uuid4().hex}"
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
        username = f"rb_{uuid4().hex[:16]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            stranger = User(username=f"other_{uuid4().hex[:16]}")
            db.add_all([owner, stranger])
            await db.flush()

            fourth = Thread(
                user_id=owner.id,
                title="Fourth World",
                format="Comic",
                queue_position=1,
                issues_remaining=2,
                total_issues=3,
            )
            jli = Thread(
                user_id=owner.id,
                title="JLI",
                format="Comic",
                queue_position=2,
                issues_remaining=2,
                total_issues=3,
            )
            miracle = Thread(
                user_id=owner.id,
                title="Mister Miracle",
                format="Comic",
                queue_position=3,
                issues_remaining=2,
                total_issues=2,
            )
            held = Thread(
                user_id=owner.id,
                title="Held Series",
                format="Comic",
                queue_position=4,
                issues_remaining=1,
                total_issues=2,
            )
            unmapped = Thread(
                user_id=owner.id,
                title="Unmapped Series",
                format="Comic",
                queue_position=5,
                issues_remaining=1,
                total_issues=1,
            )
            foreign = Thread(
                user_id=stranger.id,
                title="Private Series",
                format="Comic",
                queue_position=1,
                issues_remaining=1,
                total_issues=1,
            )
            db.add_all([fourth, jli, miracle, held, unmapped, foreign])
            await db.flush()

            issues = {
                "f1": Issue(thread_id=fourth.id, issue_number="1", position=1,
                            status="read", read_at=now - timedelta(days=20)),
                "f2": Issue(thread_id=fourth.id, issue_number="2", position=2, status="unread"),
                "f3": Issue(thread_id=fourth.id, issue_number="3", position=3, status="unread"),
                "j1": Issue(thread_id=jli.id, issue_number="1", position=1,
                            status="read", read_at=now - timedelta(days=10)),
                "j2": Issue(thread_id=jli.id, issue_number="2", position=2, status="unread"),
                "j3": Issue(thread_id=jli.id, issue_number="3", position=3, status="unread"),
                "m1": Issue(thread_id=miracle.id, issue_number="1", position=1, status="unread"),
                "m2": Issue(thread_id=miracle.id, issue_number="2", position=2, status="unread"),
                "h1": Issue(thread_id=held.id, issue_number="1", position=1,
                            status="read", read_at=now - timedelta(days=5)),
                "h2": Issue(thread_id=held.id, issue_number="2", position=2, status="unread"),
                "u1": Issue(thread_id=unmapped.id, issue_number="1", position=1, status="unread"),
                "foreign": Issue(thread_id=foreign.id, issue_number="1", position=1, status="unread"),
            }
            db.add_all(issues.values())
            await db.flush()
            fourth.next_unread_issue_id = issues["f2"].id
            jli.next_unread_issue_id = issues["j2"].id
            miracle.next_unread_issue_id = issues["m1"].id
            held.next_unread_issue_id = issues["h2"].id
            unmapped.next_unread_issue_id = issues["u1"].id
            foreign.next_unread_issue_id = issues["foreign"].id

            volumes = {
                "fourth": ExternalIdentity(
                    provider="comicvine", entity_type="series", external_id="4050-0001",
                    metadata_json={"name": "Fourth World"},
                ),
                "jli": ExternalIdentity(
                    provider="comicvine", entity_type="series", external_id="4050-0002",
                    metadata_json={"name": "JLI"},
                ),
                "miracle": ExternalIdentity(
                    provider="comicvine", entity_type="series", external_id="4050-0003",
                    metadata_json={"name": "Mister Miracle"},
                ),
                "held": ExternalIdentity(
                    provider="comicvine", entity_type="series", external_id="4050-0004",
                    metadata_json={"name": "Held Series"},
                ),
            }
            db.add_all(volumes.values())
            await db.flush()
            db.add_all(
                [
                    ThreadExternalSeriesMapping(
                        thread_id=thread.id, external_identity_id=volumes[key].id,
                        status="confirmed",
                    )
                    for key, thread in (
                        ("fourth", fourth),
                        ("jli", jli),
                        ("miracle", miracle),
                        ("held", held),
                    )
                ]
            )

            strict = CustomCBLList(
                user_id=owner.id, name="JLI strict", mode="strict"
            )
            loose = CustomCBLList(
                user_id=owner.id, name="Extra loose", mode="loose"
            )
            hold = CustomCBLList(user_id=owner.id, name="Hold list", mode="loose")
            db.add_all([strict, loose, hold])
            await db.flush()
            db.add_all(
                [
                    CustomCBLEntry(list_id=strict.id, issue_id=issues["j1"].id,
                                   position=1, gate="none"),
                    CustomCBLEntry(list_id=strict.id, issue_id=issues["m1"].id,
                                   position=2, gate="none"),
                    CustomCBLEntry(list_id=strict.id, issue_id=issues["j2"].id,
                                   position=3, gate="none"),
                    CustomCBLEntry(list_id=strict.id, issue_id=issues["m2"].id,
                                   position=4, gate="none"),
                    CustomCBLEntry(list_id=strict.id, issue_id=issues["j3"].id,
                                   position=5, gate="none"),
                    # J2 belongs to two lists; the loose list must not add a gate.
                    CustomCBLEntry(list_id=loose.id, issue_id=issues["j2"].id,
                                   position=1, gate="none"),
                    CustomCBLEntry(list_id=loose.id, issue_id=issues["m2"].id,
                                   position=2, gate="none"),
                    CustomCBLEntry(list_id=hold.id, issue_id=issues["h1"].id,
                                   position=1, gate="none"),
                    CustomCBLEntry(list_id=hold.id, issue_id=issues["h2"].id,
                                   position=2, gate="hold"),
                ]
            )
            db.add_all(
                [
                    CustomCBLOverlapDecision(
                        user_id=owner.id,
                        list_id=strict.id,
                        continuing_external_identity_id=volumes["jli"].id,
                        waiting_external_identity_id=volumes["miracle"].id,
                    ),
                    Dependency(
                        source_issue_id=issues["f2"].id,
                        target_issue_id=issues["m1"].id,
                        origin="reader",
                        classification="A",
                        provenance="Explicit reader prerequisite",
                    ),
                ]
            )
            await db.commit()

            requested = [fourth.id, jli.id, miracle.id, held.id, unmapped.id]
            canonical = await get_reading_boundary_explanations(
                db,
                user_id=owner.id,
                thread_ids=requested,
                include_historical=False,
            )
            expected = json.loads(
                json.dumps(
                    {
                        "threads": {
                            str(
                                thread_id
                            ): ReadingBoundaryExplanationV2.model_validate(
                                explanation.model_dump(exclude={"historical"})
                            ).model_dump()
                            for thread_id, explanation in canonical.threads.items()
                        }
                    }
                )
            )
            foreign_id = foreign.id

        token = jwt.encode(
            {
                "sub": username,
                "jti": "native-reading-boundary-fixture",
                "type": "access",
                "exp": int((now + timedelta(hours=1)).timestamp()),
            },
            SECRET,
            "HS256",
        )
        query = f"options=-csearch_path%3D{name}"
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url + ("&" if "?" in url else "?") + query,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_POOL_SIZE": "2",
            "RUST_ROLL_TEST_BODY": json.dumps({"thread_ids": requested}),
        }

        db_before = await _db_bytes(admin)
        result, raw, wall, cpu = await _run_example(env)
        db_after = await _db_bytes(admin)
        print(
            "native reading-boundaries parity: "
            f"http_bytes={len(raw)} wall_ms={wall * 1000:.2f} "
            f"child_cpu_ms={cpu * 1000:.2f} "
            f"db_xacts={db_after[0] - db_before[0]} "
            f"db_blocks={db_after[1] - db_before[1]}",
            flush=True,
        )

        assert result["status"] == 200, result
        assert result["body"] == expected

        env["RUST_ROLL_TEST_BODY"] = json.dumps({"thread_ids": [foreign_id]})
        denied, _, _, _ = await _run_example(env)
        assert denied["status"] == 404, denied
        assert denied["body"] == {"detail": "Thread not found"}
    finally:
        get_reading_execution_settings.cache_clear()
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        await admin.dispose()
