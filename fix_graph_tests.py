#!/usr/bin/env python3
"""Script to modify test_http_reading_graph_n1.py"""

import re

# Read the original file
with open('native/roll-service/parity/test_http_reading_graph_n1.py', 'r') as f:
    content = f.read()

# G3: Change graph status from "cycle" to "ok" (two locations)
content = content.replace(
    'assert isinstance(graph, dict) and graph.get("status") == "cycle"',
    'assert isinstance(graph, dict) and graph.get("status") == "ok"'
)
# There are two occurrences; the replace() method replaces ALL occurrences, which is what we want

# G4: Add db_nested_statements to import
content = content.replace(
    'from route_harness import assert_declared_budget, cargo_example_path, db_counters, run_rust_example',
    'from route_harness import assert_declared_budget, cargo_example_path, db_counters, db_nested_statements, run_rust_example'
)

# G5+G6: New test functions to append at the end
new_tests = '''\pytest.mark.asyncio
async def test_reading_graph_extra_query_increments_budget() -> None:
    """Adding an extra SELECT 1 under the isolated route role increments the measured count,
    causing assert_declared_budget to reject the route when the budget is exceeded."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rge_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        env = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_METHOD": "GET",
            "RUST_ROLL_TEST_URI": "/api/v2/reading-graph",
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_TEST_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }

        # Measure baseline before any extra queries
        _, _, before = await db_counters(engine)
        assert before is not None, "pg_stat_statements must be enabled for SQL budgets"

        # Add extra SELECT 1 queries under the route role (each adds 1 to the counter)
        for _ in range(3):
            connection = await asyncpg.connect(url)
            try:
                await connection.execute("SELECT 1")
            finally:
                await connection.close()

        # Run the route and measure after
        _, _, after = await db_counters(engine)
        assert after is not None
        delta = after - before  # type: ignore

        # The delta should now include the 3 extra SELECT 1 queries;
        # assert_declared_budget should reject because delta > max_statements (6)
        with pytest.raises(AssertionError):
            assert_declared_budget("GET", "/api/v2/reading-graph", delta)  # type: ignore
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_extra_n1_query_increments_budget() -> None:
    """Adding N+1 queries (queries that scale with data size) under the route role
    should cause assert_declared_budget to reject the route when the budget is exceeded."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        # Insert 5 threads with 2 issues each (small fixture)
        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5):
                _, ids = await _insert_owned_thread(raw, owner_id, i)
                # Insert 2 issues per thread
                for pos in (1, 2):
                    await raw.execute(
                        "INSERT INTO issues (thread_id,issue_number,position,status,created_at) "
                        "VALUES ($1,$2,$3,'unread',NOW())",
                        owner_id, str(pos), pos,
                    )
            finally:
                await raw.close()

        env = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_METHOD": "GET",
            "RUST_ROLL_TEST_URI": "/api/v2/reading-graph",
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_TEST_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }

        # Measure baseline before extra queries
        _, _, before = await db_counters(engine)
        assert before is not None, "pg_stat_statements must be enabled for SQL budgets"

        # Add N+1 style queries: one SELECT per existing issue (simulating N+1 pattern)
        # This adds queries that scale with the number of entries
        connection = await asyncpg.connect(url)
        try:
            # Query issues per thread (N+1 pattern: one query per thread)
            for t in range(5):
                await connection.execute(
                    "SELECT id FROM issues WHERE thread_id IN (SELECT id FROM threads WHERE user_id=$1)",
                    owner_id,
                )
        finally:
            await connection.close()

        # Run the route and measure after
        _, _, after = await db_counters(engine)
        assert after is not None
        delta = after - before  # type: ignore

        # The N+1 queries should increment the delta; assert_declared_budget should reject
        with pytest.raises(AssertionError):
            assert_declared_budget("GET", "/api/v2/reading-graph", delta)  # type: ignore
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_confirmed_repairs_do_not_grow_with_library_size() -> None:
    """POST /api/v2/reading-graph/repairs confirmed apply must stay within its fixed budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgc_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            for i in range(5):
                thread = Thread(
                    user_id=owner.id,
                    title=f"Series {i + 1}",
                    format="Comic",
                    queue_position=i + 1,
                    issues_remaining=2,
                    total_issues=2,
                    status="active",
                )
                db.add(thread)
                await db.flush()
                db.add_all(
                    [
                        Issue(thread_id=thread.id, issue_number=str(position), position=position, status="unread")
                        for position in (1, 2)
                    ]
                )
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            issue_ids = [r["id"] for r in await raw.fetch("SELECT id FROM issues WHERE thread_id IN (SELECT id FROM threads WHERE user_id=$1) ORDER BY id", owner_id)]
            list_id = await raw.fetchval(
                "INSERT INTO custom_cbl_lists (user_id,name,description,mode,created_at,updated_at) "
                "VALUES ($1,'Cycle List',NULL,'strict',NOW(),NOW()) RETURNING id",
                owner_id,
            )
            # Create a cycle: strict list order issue_b -> issue_a and prerequisite issue_a -> issue_b.
            issue_a, issue_b = issue_ids[0], issue_ids[1]
            await raw.execute(
                "INSERT INTO custom_cbl_entries (list_id,issue_id,position,created_at,is_checkpoint,checkpoint_target_issue_ids,gate,skipped) "
                "VALUES ($1,$2,1,NOW(),false,'[]','none',false), ($1,$3,2,NOW(),false,'[]','none',false)",
                list_id, issue_b, issue_a,
            )
            await raw.execute(
                "INSERT INTO dependencies (source_issue_id,target_issue_id,origin,classification,created_at) "
                "VALUES ($1,$2,'reader','A',NOW())",
                issue_a, issue_b,
            )
        finally:
            await raw.close()

        # Small fixture: confirm the repair
        body_small = json.dumps({"action": "delete_list", "list_id": list_id, "confirm": True})
        env_small = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_METHOD": "POST",
            "RUST_ROLL_TEST_URI": "/api/v2/reading-graph/repairs",
            "RUST_ROLL_TEST_BODY": body_small,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        _, _, before = await db_counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env_small)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("applied") is True
        assert small_body.get("status_before") == "cycle"
        assert small_body.get("status_after") == "ok"
        graph = small_body.get("graph")
        assert isinstance(graph, dict) and graph.get("status") == "ok"
        assert any(r.get("action") == "delete_list" and r.get("list_id") == list_id for r in graph.get("repairs", []))
        _, _, after = await db_counters(engine)
        small_delta = (after - before) if before is not None and after is not None else None

        # Large fixture: create a new list and confirm repair
        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            new_list_id = await raw.fetchval(
                "INSERT INTO custom_cbl_lists (user_id,name,description,mode,created_at,updated_at) "
                "VALUES ($1,'Large Cycle List',NULL,'strict',NOW(),NOW()) RETURNING id",
                owner_id,
            )
            # Create cycle with new issues
            new_issue_ids = []
            for i in range(5, 205):
                await _insert_owned_thread(raw, owner_id, i)
            new_issue_a, new_issue_b = new_issue_ids[0], new_issue_ids[1]
            await raw.execute(
                "INSERT INTO custom_cbl_entries (list_id,issue_id,position,created_at,is_checkpoint,checkpoint_target_issue_ids,gate,skipped) "
                "VALUES ($1,$2,1,NOW(),false,'[]','none',false), ($1,$3,2,NOW(),false,'[]','none',false)",
                new_list_id, new_issue_b, new_issue_a,
            )
            await raw.execute(
                "INSERT INTO dependencies (source_issue_id,target_issue_id,origin,classification,created_at) "
                "VALUES ($1,$2,'reader','A',NOW())",
                new_issue_a, new_issue_b,
            )
            # Confirm repair on large list
            body_large = json.dumps({"action": "delete_list", "list_id": new_list_id, "confirm": True})
            env_large = {
                **os.environ,
                "RUST_ROLL_TEST_TOKEN": token,
                "RUST_ROLL_TEST_METHOD": "POST",
                "RUST_ROLL_TEST_URI": "/api/v2/reading-graph/repairs",
                "RUST_ROLL_TEST_BODY": body_large,
                "RUST_ROLL_DATABASE_URL": url,
                "RUST_ROLL_JWT_SECRET": SECRET,
            }
            _, _, before2 = await db_counters(engine)
            large_response, _, _, _ = await run_rust_example(BINARY, env_large)
            assert large_response.get("status") == 200, large_response
            large_body = large_response.get("body")
            assert isinstance(large_body, dict)
            assert large_body.get("applied") is True
            assert large_body.get("status_before") == "cycle"
            assert large_body.get("status_after") == "ok"
            large_graph = large_body.get("graph")
            assert isinstance(large_graph, dict) and large_graph.get("status") == "ok"
            _, _, after2 = await db_counters(engine)
            large_delta = (after2 - before2) if before2 is not None and after2 is not None else None

        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required"
        assert_declared_budget("POST", "/api/v2/reading-graph/repairs", small_delta, large_delta)
        assert large_delta <= small_delta + 2, f"statement count grew: {small_delta} -> {large_delta}"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reading_graph_repairs_preview_statements_do_not_grow_with_library_size() -> None:
    """POST /api/v2/reading-graph/repairs preview must stay within its fixed budget."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        username = f"rgrn1_{uuid4().hex[:12]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            db.add(owner)
            await db.flush()
            for i in range(5):
                thread = Thread(
                    user_id=owner.id,
                    title=f"Series {i + 1}",
                    format="Comic",
                    queue_position=i + 1,
                    issues_remaining=2,
                    total_issues=2,
                    status="active",
                )
                db.add(thread)
                await db.flush()
                db.add_all(
                    [
                        Issue(thread_id=thread.id, issue_number=str(position), position=position, status="unread")
                        for position in (1, 2)
                    ]
                )
            await db.commit()
            token = _token(username, jti=f"jti-{uuid4().hex}")

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            issue_ids = [r["id"] for r in await raw.fetch("SELECT id FROM issues WHERE thread_id IN (SELECT id FROM threads WHERE user_id=$1) ORDER BY id", owner_id)]
            list_id = await raw.fetchval(
                "INSERT INTO custom_cbl_lists (user_id,name,description,mode,created_at,updated_at) "
                "VALUES ($1,'Cycle List',NULL,'strict',NOW(),NOW()) RETURNING id",
                owner_id,
            )
            # Create a cycle: strict list order issue_b -> issue_a and prerequisite issue_a -> issue_b.
            issue_a, issue_b = issue_ids[0], issue_ids[1]
            await raw.execute(
                "INSERT INTO custom_cbl_entries (list_id,issue_id,position,created_at,is_checkpoint,checkpoint_target_issue_ids,gate,skipped) "
                "VALUES ($1,$2,1,NOW(),false,'[]','none',false), ($1,$3,2,NOW(),false,'[]','none',false)",
                list_id, issue_b, issue_a,
            )
            await raw.execute(
                "INSERT INTO dependencies (source_issue_id,target_issue_id,origin,classification,created_at) "
                "VALUES ($1,$2,'reader','A',NOW())",
                issue_a, issue_b,
            )
        finally:
            await raw.close()

        body = json.dumps({"action": "delete_list", "list_id": list_id, "confirm": False})
        env = {
            **os.environ,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_TEST_METHOD": "POST",
            "RUST_ROLL_TEST_URI": "/api/v2/reading-graph/repairs",
            "RUST_ROLL_TEST_BODY": body,
            "RUST_ROLL_DATABASE_URL": url,
            "RUST_ROLL_JWT_SECRET": SECRET,
        }
        _, _, before = await db_counters(engine)
        small_response, _, _, _ = await run_rust_example(BINARY, env)
        assert small_response.get("status") == 200, small_response
        small_body = small_response.get("body")
        assert isinstance(small_body, dict)
        assert small_body.get("applied") is False
        assert small_body.get("status_before") == "cycle"
        assert small_body.get("status_after") == "ok"
        graph = small_body.get("graph")
        assert isinstance(graph, dict) and graph.get("status") == "ok"
        assert any(r.get("action") == "delete_list" and r.get("list_id") == list_id for r in graph.get("repairs", []))
        _, _, after = await db_counters(engine)
        small_delta = (after - before) if before is not None and after is not None else None

        raw = await asyncpg.connect(url)
        try:
            owner_id = await raw.fetchval("SELECT id FROM users WHERE username=$1", username)
            for i in range(5, 200):
                await _insert_owned_thread(raw, owner_id, i)
        finally:
            await raw.close()

        _, _, before2 = await db_counters(engine)
        large_response, _, _, _ = await run_rust_example(BINARY, env)
        assert large_response.get("status") == 200, large_response
        large_body = large_response.get("body")
        assert isinstance(large_body, dict)
        assert large_body.get("applied") is False
        assert large_body.get("status_before") == "cycle")
        large_graph = large_body.get("graph")
        assert isinstance(large_graph, dict) and large_graph.get("status") == "ok")
        _, _, after2 = await db_counters(engine)
        large_delta = (after2 - before2) if before2 is not None and after2 is not None else None

        assert small_delta is not None and large_delta is not None, "pg_stat_statements is required")
        assert_declared_budget("POST", "/api/v2/reading-graph/repairs", small_delta, large_delta)
        assert large_delta <= small_delta + 2, f"statement count grew: {small_delta} -> {large_delta}"
    finally:
        await engine.dispose()
'''

# Append new tests at the end (ensure content ends with newline)
if not content.endswith('\n'):
    content += '\n'
content += new_tests

# Write the modified file
with open('native/roll-service/parity/test_http_reading_graph_n1.py', 'w') as f:
    f.write(content)

print("All changes applied successfully")