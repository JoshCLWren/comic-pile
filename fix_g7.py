#!/usr/bin/env python3
with open('native/roll-service/parity/test_http_reading_lists_n1.py', 'r') as f:
    content = f.read()

# Fix the _get_last_list_id reference - replace the large_list_delta section
old = """large_list_id = await _get_last_list_id(engine, owner_id)  # helper would be needed
        # Instead, read the large list we just created and delete it
        env3 = _run_env(token, "DELETE", f"/api/v2/reading-lists/LargeList")
        _, _, before3 = await db_counters(engine)
        large_list, _, _, _ = await run_rust_example(BINARY, env3)
        assert large_list.get("status") == 204, large_list
        _, _, after3 = await db_counters(engine)
        large_list_delta = (after3 - before3) if before3 is not None and after3 is not None else None

        assert small_delta is not None and large_delta is not None and large_list_delta is not None
        assert_declared_budget("DELETE", "/api/v2/reading-lists/{list_id}", small_delta, large_delta)
        assert_declared_budget("DELETE", "/api/v2/reading-lists/{list_id}", small_delta, large_list_delta)
        assert large_delta <= small_delta + 2, f"statement count grew: {small_delta} -> {large_delta}"
        assert large_list_delta <= small_delta + 2, f"large list delta grew: {small_delta} -> {large_list_delta}" """

new = """# Also delete the large seeded list to verify long-list deletion is bounded
        env3 = _run_env(token, "DELETE", f"/api/v2/reading-lists/LargeList")
        _, _, before3 = await db_counters(engine)
        large_list, _, _, _ = await run_rust_example(BINARY, env3)
        assert large_list.get("status") == 204, large_list
        _, _, after3 = await db_counters(engine)
        large_list_delta = (after3 - before3) if before3 is not None and after3 is not None else None

        assert small_delta is not None and large_delta is not None and large_list_delta is not None
        assert_declared_budget("DELETE", "/api/v2/reading-lists/{list_id}", small_delta, large_delta)
        assert_declared_budget("DELETE", "/api/v2/reading-lists", small_delta, large_list_delta)
        assert large_delta <= small_delta + 2, f"statement count grew: {small_delta} -> {large_delta}"
        assert large_list_delta <= small_delta + 2, f"large list delta grew: {small_delta} -> {large_list_delta}" """

content = content.replace(old, new)

with open('native/roll-service/parity/test_http_reading_lists_n1.py', 'w') as f:
    f.write(content)
print("Fixed G7 test")