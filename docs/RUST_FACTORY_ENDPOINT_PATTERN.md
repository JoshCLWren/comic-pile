# Rust API endpoint implementation pattern

Use this as an implementation checklist, not an alternative API architecture. The authoritative product contract is #4335 and its latest owner decisions. Preserve the exact resource contract and migrate the real caller; do not create a parallel unused endpoint, temporary feature flag, or Python fallback.

## Implementation checklist

1. Start from `native/roll-service/src/lib.rs` and the owning resource module. Preserve `AuthenticatedUser`, `AppState`, `ApiError`, the bounded DB pool, owner-scoped SQL, and transaction boundaries.
2. Define request/response DTOs with `serde`/`utoipa`. Validate bounds, nullability, errors, and ownership before database work.
3. Register the exact HTTP method/path in the service router and the separate Vercel ingress router in `api/native_roll.rs`. Both tables must agree; an ingress omission produces a Rust JSON 404 before the handler runs.
4. Express production routing in `docs/api/route-fragments/*.json`. Never hand-edit `vercel.json`, `docs/api/v2-route-inventory.json`, `docs/api/route-fragments/vercel-rewrites.json`, or the generated `AGENTS.md` route block. The route-regeneration workflow owns those outputs.
5. Switch the real caller under `frontend/src/services/`, regenerate contracts/types, and add focused frontend tests. Do not infer implementation language from an API version.
6. For writes, use owner-scoped SQL in a transaction, serialize concurrent writers where required, preserve idempotency/locking, and assert the resulting rows. Add a disposable-PostgreSQL HTTP test for the route.
7. Verify route precedence and wrong-method behavior with method/path lookups rather than fixed route indexes. Keep unrelated routes intact when reconciling branch drift.
8. After exact-head CI and independent review, verify a successful authenticated production request uses the Rust entrypoint and achieves the requested behavior.

## Focused checks

```bash
cargo test --locked -p comicpile-roll-service <module-or-filter>
node scripts/generate_vercel_routes.mjs
node scripts/generate_route_burndown.mjs
node scripts/generate_vercel_routes.mjs --check
node scripts/generate_route_burndown.mjs --check
node --test scripts/generate_vercel_routes.test.mjs scripts/vercel_slim_routes.test.mjs
node scripts/export_openapi_schema.mjs --check
node scripts/generate_openapi_types.mjs --check
node scripts/check_native_route_db_tests.mjs
```

The generator sequence above mutates generated outputs in a disposable validation checkout; do not include bot-owned outputs in the PR. CI validates the resolved ingress and current Rust/Node contract tests. DB-backed tests require `RUST_ROLL_TEST_DATABASE_URL` and must use disposable PostgreSQL, never production.

The retired Python endpoint-oracle scripts/tests are historical and must not be used as current gates. The current witnesses are Rust DB-backed HTTP tests, Rust contract drift tests, Node route/generator tests, frontend type checks, and exact-head CI.

## Quality measurement

The read-only first-head scorecard runs from `.github/workflows/rust-first-head-quality.yml`. Its retained artifacts distinguish passed, failed, cancelled, incomplete, and missing first-head runs; they do not authorize merging or classify root cause without investigation.

```bash
python scripts/report_rust_first_head_ci.py --since 2026-10-29 --format markdown
```
