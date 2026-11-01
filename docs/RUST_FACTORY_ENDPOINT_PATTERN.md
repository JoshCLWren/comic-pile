# Rust API cutover: endpoint implementation pattern

Use this as an implementation checklist, not an alternative API architecture. The
authoritative product contract is #4335 and its latest owner decisions. Preserve
the precise resource-oriented v2 contract and migrate the **actual frontend
caller**. Do not create a parallel unused endpoint, temporary feature flag, or
Python fallback.

## Copy the existing working structure

1. Start from the current canonical Rust service:
   `native/roll-service/src/lib.rs`. For owned issue writes, inspect
   `issue_handler.rs` and its transaction-bound `issue_service.rs::persist`.
   For batch reads, inspect `reading_boundary.rs`. Preserve the established
   `AuthenticatedUser` extractor, `AppState`, `ApiError`, bounded DB pool
   and owner-scoped SQL. Never hardcode a user ID or return mock success values.
2. Define the request and response using the canonical OpenAPI shape. Validate
   bounds, errors and 404/422 behavior against the existing route and frontend
   expectations, including null versus absent JSON fields.
3. Add the exact HTTP **method and path** in the service router in `lib.rs`,
   then register the same handler in the real ingress (`api/native_roll.rs`
   or `api/native_issue.rs`) and add the method-specific `vercel.json`
   rewrite **before** the catch-all. Test both allowed and rejected methods,
   numeric IDs, route precedence and security headers.
4. Trace and switch the real caller under `frontend/src/services/`. Update
   generated API types, tests, and API oracle/parity tests as needed. Do not
   infer an implementation language from an API version.
5. For writes, use owner-scoped SQL within a transaction, serialize concurrent
   modifications when necessary, persist idempotency receipts, and check the
   resulting database state. A mock, auth-only or read-only test does not prove
   a mutation. The HTTP write-path guard covers POST, PATCH, PUT and DELETE.
6. Protect the exact behavior with disposable-PostgreSQL tests and targeted
   frontend/ingress checks. For direct read/rate, see
   `native/roll-service/src/issue_service.rs` and
   `native/roll-service/parity/test_http_issue_read_rate.py`. For ingress
   checks, see `tests/test_native_roll_live_ingress.py`,
   `tests/test_native_roll_write_test_guard.py`, and
   `tests/test_vercel_deployment.py`.
7. Deploy only after exact-head CI and independent semantic review. Confirm a
   successful authenticated production request used the Rust entrypoint and
   achieved the requested behavior. Keep the owner objective open until
   applicable caller migration, deletion and production acceptance are done.

## Pre-push checks

From the repository root:

```bash
bash scripts/check-rust-factory-prepush.sh
uv run --frozen pytest -q -x --no-cov \
  tests/test_native_roll_live_ingress.py \
  tests/test_native_roll_write_test_guard.py \
  tests/test_vercel_deployment.py
```

The first command checks both native Rust compilation surfaces using the same
toolchain choices as `.github/workflows/rust-roll.yml` (service: pinned
1.85.0) and `.github/workflows/native-vercel-rust.yml` (root: stable).
The trusted factory wrapper runs these checks automatically for Rust or native
ingress changes. Targeted service tests requiring `RUST_ROLL_TEST_DATABASE_URL`
must use **disposable** PostgreSQL, never the production database. Full suite,
parity, migration health, and the remaining gates run in CI.

The worker's pre-push toolchain is a prerequisite, not evidence that CI passed.
If compilation cannot run, fail closed and preserve a truthful handoff rather
than pretending the code was verified or weakening the tests.
