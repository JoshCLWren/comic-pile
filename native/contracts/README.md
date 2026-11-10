# Python endpoint references for native ports

`roll-bootstrap-v1.openapi.json` is the transitive operation snapshot from
`frontend/src/generated/openapi.json` at production commit `cdaa74f`, for
GET `/api/v1/roll/bootstrap` (#4350). It includes nested models, security
schemes and query defaults. Arrays retain their original ordering. The Python handler and its PostgreSQL-backed port-oracle test were both
removed by #4397, so this file is a frozen comparison baseline for the native
port, not a live oracle.

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
reading-session initialization, the dice/offer/reset commands, the scoped
`GET /api/v2/roll/die-state` and `GET /api/v2/roll/eligible-issue-ids` resources
(#4595), the reading-boundaries batch, and the queue, thread and issue resources
already published by `QueueApi`, `ThreadsApi` and `IssueApi`. It is generated
only from Rust declarations (`comicpile_roll_service::openapi::canonical_openapi`),
which merges the per-domain `utoipa::OpenApi` documents instead of duplicating a
spec. Regenerate it with:

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

The normal consumer is `frontend/src/services/rollBootstrapApi.ts`; recovery
uses `frontend/src/services/protectedRollMutationApi.ts`. Both already call
`/api/v2/roll/bootstrap`. The legacy `/api/roll/bootstrap` and
`/api/v1/roll/bootstrap` aliases were removed with the Python handler (#4397)
and now fall through to the Python catch-all. V2 is a separate contract.

`GET /api/v2/analytics/metrics` (#4348) is documented by
`comicpile_roll_service::analytics::AnalyticsApi`. Emit its operation with:

```sh
cd native/roll-service
cargo run --example analytics_openapi
```

`bug-reports-v1.openapi.json` is the generated native contract for the
same-path bug-report slice `POST /api/bug-reports/` and
`POST /api/v1/bug-reports/` (#4852, Part of #4335). Regenerate it with:

```sh
cd native/roll-service
cargo run --example bug_reports_openapi > ../contracts/bug-reports-v1.openapi.json
```

It is generated only from `comicpile_roll_service::bug_reports::BugReportsApi`
and preserves the Python wire contract (201 `issue_url`, 401/422/429/502/503)
at the exact same method/paths. Python handlers remain until production
proof; the frontend caller (`frontend/src/services/api-bug-reports.ts`)
keeps calling `/v1/bug-reports/` unchanged.

`session-detail-v1.openapi.json` is the generated native contract for the
same-path single-session slice `GET /api/sessions/{session_id}` and
`GET /api/v1/sessions/{session_id}` (#4839, Part of #4335). Regenerate it
with:

```sh
cd native/roll-service
cargo run --example session_detail_openapi > ../contracts/session-detail-v1.openapi.json
```

It is generated only from
`comicpile_roll_service::session_detail::SessionDetailApi` and preserves
the Python wire contract (owner-scoped `Session not found` 404, ladder
path, current die, active thread, bandwidth/intent normalization) at the
exact same method/paths. Python handlers remain until production proof;
the frontend caller (`frontend/src/services/api-sessions.ts`) keeps
calling `/v1/sessions/{id}` unchanged.

The unified Rust-derived contract and generated TS client are owned by #4457; this
repository does not hand-author a second analytics schema. The merged generated
client schema temporarily retains the legacy Python v1/bare analytics operation
until #4348's authenticated production proof permits the post-proof cleanup.

`preferences-v1.openapi.json` is the generated native contract for the
same-path preferences and Taste Bank signal cutover in #4834:
`GET`/`PATCH /api/v1/users/me/preferences`,
`GET /api/v1/users/me/taste-signals` and
`PUT /api/v1/users/me/taste-signals/{signal_type}/{external_key}/verdict`.
It is generated only from Rust declarations
(`comicpile_roll_service::preferences::PreferencesApi`) and is not part of
the `/api/v2` aggregate (`v2-runtime.openapi.json`), because these browser
callers keep their `/api/v1` URLs. Regenerate it with:

```sh
cd native/roll-service
cargo run --example preferences_openapi > ../contracts/preferences-v1.openapi.json
```

Its checked-in drift test is
`preferences::tests::checked_in_openapi_contract_is_current`. The Python
handlers stay mounted until authenticated production proof permits their
removal; the schemas here match the Python `UserPreferences*` and
`TasteSignal*`/`TasteVerdictRequest` contracts field for field.

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

The retired `tests/test_roll_bootstrap_port_oracle.py` executed the original
Python v1 handler, validated its response against the frozen schema and recorded
the emitted SQL, bind shapes and connection transaction events as
`roll-bootstrap-v1.sql.json` in the CI `rust-sql-oracle-*` artifact. The oracle was removed with the Python handler (#4397); its transcript is
historical evidence only.

The captured transcript covered one representative existing-session path, not a
complete SQL inventory: new-session creation, pending recovery, and timezone
updates still needed targeted captures. Do not substitute those queries for the
unrecorded branches or treat the file as proof they are equivalent.

Run the focused reference check:

```sh
pytest tests/test_rust_endpoint_oracle.py --no-cov
```

This infrastructure does not change ingress. The Python bootstrap handlers and
read model are removed (#4397, #4350); deleting the native Rust v2 handler
remains #4299's scope.
