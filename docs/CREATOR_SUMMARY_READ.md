# Requested creator summary reads

The current browser caller uses native `GET /api/v2/creators/summaries`, implemented in `native/roll-service/src/creators_v2.rs`. The retained `/api/v1/creators/summaries` compatibility path also runs in native Rust; it is not the retired Python repository path.

The v2 reader scopes stored manual credits and provider credits to the authenticated reader, computes global rated/read-unrated/upcoming coverage in PostgreSQL, and returns only requested creator attribution with effective ratings. Confirmed credits suppress manual fallback independently of the requested IDs. Queries are set-based and bounded; unrelated owned issues are not materialized for a small requested set.

Current DB-backed coverage lives in `native/roll-service/tests/creators_v2_http.rs` and the focused creator tests. Run a targeted case with:

```bash
RUST_ROLL_TEST_DATABASE_URL=postgresql://... \
  cargo test --locked -p comicpile-roll-service --test creators_v2_http <filter>
```

The former `app/repositories/creator_summary.py` implementation and Python performance test are historical. <!-- docs-path-check: ignore --> Reduced transferred rows alone are not an end-to-end latency guarantee; profile a demonstrated regression before changing query shape.
