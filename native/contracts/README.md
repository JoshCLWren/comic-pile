# Python endpoint references for native ports

`roll-bootstrap-v1.openapi.json` is the transitive operation snapshot from
`frontend/src/generated/openapi.json` at production commit `cdaa74f`, for
GET `/api/v1/roll/bootstrap` (#4350). It includes nested models, security
schemes and query defaults. Arrays retain their original ordering. The
PostgreSQL-backed test also compares it with the live FastAPI `app.openapi()`
operation, so a stale generated client file cannot silently become the oracle.

`issue-v2.openapi.json` is the generated native contract for the new product
behaviour in #4443: `PATCH /api/v2/issues/{issue_id}` and the bounded
`POST /api/v2/issues/cards` projection. Regenerate it with:

```sh
cd native/roll-service
cargo run --example issue_openapi > ../contracts/issue-v2.openapi.json
```

The Rust test `checked_in_openapi_contract_is_current` fails when the checked-in
file drifts from `IssueApi::openapi()`. This is the canonical Rust contract, not
a FastAPI-generated operation; the coordinated frontend client and caller
cutover remain #4444/#4337 work.

Every `*-v2.openapi.json` file here is also validated by
`tests/test_native_v2_contract_artifacts.py`: the document must be OpenAPI 3.1
with component schemas, every path must live under `/api/v2/`, no path may use a
colon-method or verb-shaped action segment, and every operation must declare a
generated `operationId`, bearer security and a 2xx response. New Rust v2
target-resource contracts are picked up by that guard automatically.

`v2-runtime.openapi.json` is the aggregate contract for **every deployed native
`/api/v2` operation** (#4457): the eight auth endpoints, Roll bootstrap and
reading-session initialization, the dice/offer/reset commands, the
reading-boundaries batch, and the queue, thread and issue resources already
published by `QueueApi`, `ThreadsApi` and `IssueApi`. It is generated only from
Rust declarations (`comicpile_roll_service::openapi::canonical_openapi`), which
merges the per-domain `utoipa::OpenApi` documents instead of duplicating a spec.
Regenerate it with:

```sh
cd native/roll-service
cargo run --example v2_openapi > ../contracts/v2-runtime.openapi.json
```

Its checked-in drift test is
`openapi::tests::checked_in_runtime_contract_is_current`, and
`openapi::tests::covers_every_deployed_native_v2_operation` pins the exact
method/path surface. The aggregate intentionally includes public auth entry
points, so the artifact guard checks explicit security declarations rather than
requiring bearer auth on every operation.

`scripts/export_openapi_schema.py` merges this contract into the single
client-facing document (`frontend/src/generated/openapi.json`) and then
`scripts/generate_openapi_types.py` regenerates `openapi.ts` plus the thin
`nativeV2Client.ts` request client. A native operation replaces the same
`(path, method)` FastAPI operation because ingress sends that request to Rust.
A component-name collision is renamed `Native<Name>` with every reference
inside the native subtree rewritten; an identical schema is reused.
`nativeV2Client.ts` is generated from the native operation set and the merged
operation types, and every method delegates to the caller-provided
`HttpClient`; it is not a second transport and does not reimplement auth, CSRF,
retries or error handling. Its `--check` drift runs in the same canonical
generator boundary and never rewrites repository artifacts from custom-schema
runs.
`docs/api/v2-route-inventory.json` records the observed runtime and declared
consumers for each live v2 operation, and
`tests/test_api_v2_contract_inventory.py` fails when the inventory, the native
contract, the generated schema, `vercel.json` or a frontend service caller
drifts.

`threads-v2.openapi.json` is the generated native contract for
`GET /api/v2/threads` (#4342). Regenerate it with:

```sh
cd native/roll-service
cargo run --example threads_openapi > ../contracts/threads-v2.openapi.json
```

Its checked-in drift test is `threads::tests::checked_in_openapi_contract_is_current`.
The normal consumer is `frontend/src/services/api-threads.ts` (`list` only; the
remaining thread mutations stay on their existing v1 paths).

The real normal consumer is `frontend/src/services/rollBootstrapApi.ts`.
Recovery uses `frontend/src/services/protectedRollMutationApi.ts`. Both keep
their existing v1 URL. The legacy `/api/roll/bootstrap` alias shares the Python
handler and must also move before Python deletion. V2 is a separate contract.

To compare an independently generated Rust OpenAPI operation:

```sh
python scripts/rust_endpoint_oracle.py check \
  --schema /tmp/rust-generated-openapi.json \
  --contract native/contracts/roll-bootstrap-v1.openapi.json
```

The comparison includes the full referenced component closure, not only the
top-level response. It must receive actual native-generated output. The frozen
Python file alone does not establish native parity, runtime behavior, or a
production cutover.

`tests/test_roll_bootstrap_port_oracle.py` executes the original Python v1
handler against fixture-owned synthetic PostgreSQL data, including pool,
snoozed, skipped, blocked, stale, completed and deprioritized sections. It
validates the response against the frozen schema and records every emitted
statement, driver bind type/container shape, bind order when available, and
connection transaction events. Scalars are never recorded. The transcript is
available as `roll-bootstrap-v1.sql.json` in the CI `rust-sql-oracle-*` artifact
for the shard running that test. A failed test does not export a success artifact.

This is one representative existing-session path, not a complete SQL inventory:
new-session creation, pending recovery, and timezone updates still need targeted
captures as the native handler is implemented. Do not substitute these queries
for those unrecorded branches or treat the file as proof they are equivalent.

Run the focused reference checks:

```sh
pytest tests/test_rust_endpoint_oracle.py tests/test_roll_bootstrap_port_oracle.py --no-cov
```

This infrastructure does not change ingress, implement Rust v1, or delete
Python. #4350 stays open until the actual contract-preserving native deployment
and the subsequent Python-deletion deployment both succeed.
