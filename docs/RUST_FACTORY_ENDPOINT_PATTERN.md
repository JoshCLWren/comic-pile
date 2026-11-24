# Rust API endpoint implementation pattern

Use this as an implementation checklist, not an alternative architecture. The
authoritative contract is the current owner decision and `AGENTS.md`. Preserve
the real frontend caller and wire contract; do not create an unused parallel
endpoint, feature flag or Python fallback.

## Implementation checklist

1. Start from `native/roll-service/src/lib.rs` and the relevant domain module.
   Preserve `AuthenticatedUser`, `AppState`, `ApiError`, the bounded pool and
   owner-scoped SQL. Never hardcode a user ID or return mock success.
2. Define request/response DTOs with `serde` / `utoipa`. Validate bounds, nulls,
   errors and 404/422 behavior against the existing caller and generated contract.
3. Register the exact method/path in the native router. Add a DB-backed HTTP test
   under `native/roll-service/tests/`; `node scripts/check_native_route_db_tests.mjs`
   enforces coverage.
4. Switch the real caller under `frontend/src/services/` only when the approved
   contract calls for it. API version is not implementation language.
5. For writes, use owner-scoped SQL in a transaction, serialize concurrent
   mutations where required, persist idempotency receipts and assert resulting
   rows. Auth-only or read-only tests do not prove a mutation.
6. Regenerate native and client OpenAPI artifacts with the commands in
   [`native/contracts/README.md`](../native/contracts/README.md).
7. Edit only source route fragments under `docs/api/route-fragments/`. Never
   hand-edit `vercel.json`, the generated inventory or the `AGENTS.md`
   route-burndown block; the post-merge route workflow owns those outputs.
8. Run focused local checks, exact-head CI and independent semantic review.
   Confirm a successful authenticated production request in the intended runtime
   before removing an old implementation.

## Ingress tests

Use method/path/entrypoint lookups in `scripts/generate_vercel_routes.test.mjs`
and `scripts/vercel_slim_routes.test.mjs`. Do not use route-index assertions,
fixed native-route counts or mass index updates. Test allowed/rejected methods,
numeric IDs, precedence and wrong-method fallback.

The production workflow regenerates fragment-derived routes, verifies them and
then strips retired build functions. A stale checked-in generated artifact is not
a reason to hand-edit bot-owned output.

## Focused validation

```bash
cargo check --workspace
cargo test -p comicpile-roll-service <module-or-test-filter>
node --test scripts/generate_vercel_routes.test.mjs scripts/vercel_slim_routes.test.mjs
node scripts/check_native_route_db_tests.mjs
node scripts/generate_openapi_types.mjs --check
```

`scripts/check-rust-factory-prepush.sh` is an additional workspace check. Tests
requiring `RUST_ROLL_TEST_DATABASE_URL` must use disposable PostgreSQL. Full
workspace, migration and frontend suites run in CI.

Do not claim the retired `tests/test_native_roll_live_ingress.py`,
`tests/test_native_roll_write_test_guard.py` or `tests/test_vercel_deployment.py`
files still exist; they were removed with the Python runtime.

## Branch drift

Start from current `main`. Resolve genuine conflicts semantically and preserve
newer routes. Do not enable automatic rebases that repeatedly invalidate
exact-head CI/reviews or interfere with live factory leases.
