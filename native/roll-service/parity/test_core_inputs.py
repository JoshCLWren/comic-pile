"""Compare native scalar inputs with the Python oracle on isolated disposable schemas."""

import asyncio
import json
import os
import resource
import time
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.models import Issue, Thread, User
from app.repositories.reading_shadow_repository import load_shadow_inputs

ROOT = Path(__file__).resolve().parents[3]
SECRET = "synthetic-core-parity-secret"


@pytest.mark.asyncio
async def test_core_scalar_parity() -> None:
    """Exercise natural order, inactive sources, stale flags, and foreign frontiers."""
    url = os.environ.get("RUST_ROLL_TEST_DATABASE_URL")
    if url is None:
        pytest.skip(
            "disposable test Postgres (RUST_ROLL_TEST_DATABASE_URL) is not available"
        )
    schema = f"native_core_{uuid4().hex}"
    admin = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        url.replace("postgresql://", "postgresql+asyncpg://"),
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            reader, foreign = User(username="core-reader"), User(username="foreign-reader")
            db.add_all([reader, foreign])
            await db.flush()
            active = Thread(
                user_id=reader.id,
                title="Active",
                format="Comic",
                status="active",
                queue_position=50,
                is_blocked=True,
            )
            inactive = Thread(
                user_id=reader.id,
                title="Inactive source",
                format="Comic",
                status="completed",
                queue_position=0,
            )
            empty = Thread(
                user_id=reader.id, title="Empty", format="Comic", status="active", queue_position=-4
            )
            other = Thread(
                user_id=foreign.id,
                title="Private foreign title",
                format="Comic",
                status="active",
                queue_position=1,
            )
            db.add_all([active, inactive, empty, other])
            await db.flush()
            # Insert in an order different from natural position and issue-number order.
            later = Issue(thread_id=active.id, issue_number="10", position=2, status="unread")
            first = Issue(thread_id=active.id, issue_number="2", position=1, status="read")
            source = Issue(thread_id=inactive.id, issue_number="1", position=1, status="read")
            private = Issue(thread_id=other.id, issue_number="secret", position=1, status="unread")
            db.add_all([later, first, source, private])
            await db.flush()
            active.next_unread_issue_id = later.id
            await db.commit()
            reader_id, active_id, other_id, private_id = reader.id, active.id, other.id, private.id
        async with engine.connect() as connection:
            connection = await connection.execution_options(isolation_level="REPEATABLE READ")
            async with connection.begin():
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                async with AsyncSession(bind=connection) as db:
                    started_cpu, started_wall = time.process_time(), time.perf_counter()
                    oracle = await load_shadow_inputs(
                        db, reader_id, include_legacy_diagnostics=False
                    )
                    python_cpu = time.process_time() - started_cpu
                    python_wall = time.perf_counter() - started_wall
        expected = {
            "threads": [
                {
                    "id": row.thread_id,
                    "status": row.status,
                    "title": dict(oracle.thread_labels)[row.thread_id],
                }
                for row in sorted(oracle.threads, key=lambda row: row.thread_id)
            ],
            "issues": [
                {
                    "id": row.issue_id,
                    "thread_id": row.thread_id,
                    "position": row.position,
                    "status": row.status,
                    "issue_number": dict(oracle.issue_numbers)[row.issue_id],
                }
                for row in sorted(
                    oracle.issues, key=lambda row: (row.thread_id, row.position, row.issue_id)
                )
            ],
            "stored": [asdict(row) for row in oracle.stored],
        }
        token = jwt.encode(
            {"sub": "core-reader", "jti": "core-test", "type": "access"}, SECRET, "HS256"
        )
        separator = "&" if "?" in url else "?"
        environment = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": f"{url}{separator}application_name={schema}&options=-csearch_path%3D{schema}",
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": token,
        }
        binary = ROOT / "native/roll-service/target/debug/examples/reading_snapshot"

        async def run() -> tuple[int, bytes, bytes]:
            process = await asyncio.create_subprocess_exec(
                str(binary),
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
                return process.returncode or 0, stdout, stderr
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()

        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.perf_counter()
        status, stdout, stderr = await run()
        rust_wall = time.perf_counter() - started
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        assert status == 0, stderr.decode()
        assert json.loads(stdout) == expected
        print(
            {
                "python_oracle_cpu_s": python_cpu,
                "python_oracle_wall_s": python_wall,
                "rust_process_cpu_s": after.ru_utime
                + after.ru_stime
                - before.ru_utime
                - before.ru_stime,
                "rust_process_wall_s": rust_wall,
                "native_data_queries": 2,
            }
        )
        # Force a commit between the two native data SELECTs. The issues query
        # blocks behind this lock after the thread query established the snapshot.
        async with engine.begin() as writer:
            await writer.execute(text("LOCK TABLE issues IN ACCESS EXCLUSIVE MODE"))
            pending = asyncio.create_task(run())
            for _ in range(100):
                async with admin.connect() as observer:
                    blocked = await observer.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE application_name = :name "
                            "AND wait_event_type = 'Lock' AND query LIKE 'SELECT i.id,%'"
                        ),
                        {"name": schema},
                    )
                if blocked:
                    break
                await asyncio.sleep(0.01)
            else:
                pending.cancel()
                pytest.fail("native issues query did not reach the controlled lock")
            await writer.execute(
                text("UPDATE threads SET status = 'completed' WHERE id = :id"), {"id": active_id}
            )
            await writer.execute(
                text("UPDATE issues SET status = 'read' WHERE id = :id"), {"id": later.id}
            )
        status, stdout, stderr = await pending
        assert status == 0, stderr.decode()
        assert json.loads(stdout) == expected
        # Verify the transaction settings on the server while executing the
        # production SELECT. The view exists only in this isolated test schema.
        async with engine.begin() as connection:
            await connection.execute(text("ALTER TABLE threads RENAME TO scalar_threads"))
            await connection.execute(
                text("""
                CREATE FUNCTION assert_snapshot() RETURNS boolean LANGUAGE plpgsql AS $$
                BEGIN
                    IF current_setting('transaction_read_only') <> 'on'
                       OR current_setting('transaction_isolation') <> 'repeatable read' THEN
                        RAISE EXCEPTION 'unsafe snapshot';
                    END IF;
                    RETURN true;
                END $$
            """)
            )
            await connection.execute(
                text("CREATE VIEW threads AS SELECT * FROM scalar_threads WHERE assert_snapshot()")
            )
        status, _, stderr = await run()
        assert status == 0, stderr.decode()
        async with engine.begin() as connection:
            await connection.execute(text("DROP VIEW threads"))
            await connection.execute(text("ALTER TABLE scalar_threads RENAME TO threads"))
        # Model constraints normally prevent corruption. Deliberately remove that
        # constraint only in this disposable schema to verify the runtime boundary.
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE threads DROP CONSTRAINT fk_threads_frontier_same_thread")
            )
        for pointer in (private_id, source.id):
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE threads SET next_unread_issue_id = :pointer WHERE id = :thread"),
                    {"pointer": pointer, "thread": active_id},
                )
            status, stdout, stderr = await run()
            assert status != 0
            assert not stdout
            assert b"Unresolved reading reference" in stderr
            assert b"Private foreign" not in stderr
        assert other_id != active_id
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
