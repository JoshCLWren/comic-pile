# Retained native v1 and unversioned API contracts

New client resources use `/api/v2/*`. Existing v1 and unversioned operations
remain only where the native route registry and
[`same-path-runtime.openapi.json`](../native/contracts/same-path-runtime.openapi.json)
still publish them. They run in native Rust; the version segment does not identify
a language.

## Authoritative sources

- `native/roll-service/src/lib.rs` is the mounted route registry.
- `native/contracts/same-path-runtime.openapi.json` is the generated native
  same-path contract.
- `frontend/src/services/` identifies actual first-party callers.
- [`docs/API.md`](API.md) explains current route families and retired surfaces.

`docs/api/v2-route-inventory.json` is the generated v2 cutover inventory. Its
`full_surface` section describes the retired Python-handler surface and
fragment-owned v1 operations; it is **not** an exhaustive list of native v1
compatibility routes.

## Retained examples

The same-path contract includes, among others:

- Auth compatibility handlers under `/api/v1/auth/*` and `/api/auth/*`; product
  clients use `/api/v2/auth/*`.
- Thread lifecycle/detail, issue-list, blocking-info and dependency reads under
  `/api/v1/threads...`.
- CBL catalog reads and adoption previews under
  `/api/v1/issue-identity/cbl-sources...` and `/api/v1/issue-identity/cbl...`.
- Creator summaries, taste discoveries/signals, release publishing/retraction and
  continuity-rule operations retained for existing callers.
- `POST /api/v1/bug-reports/` and `POST /api/bug-reports/`.
- `GET /api/metrics` and the recommendation-explanation compatibility reads.

Use the generated method/path list for exact contracts; this narrative is not a
second route table.

## Retired examples

- `POST /api/v1/roll/` and `POST /api/roll/` are retired; use the v2 Roll
  resources.
- `POST /api/v1/rate/` and `POST /api/rate/` are retired; use
  `PATCH /api/v2/issues/{issue_id}`.
- Session list/single-session GETs and their unversioned aliases are retired;
  use `/api/v2/reading-sessions/{session_id}/details` and `/snapshots`.
- Queue move/shuffle action routes, old health/docs routes and Python admin
  import/export routes are absent.
- Collections and the former `/api/v1/prerequisites/` authoring API are absent.
  Canonical execution accepts only existing deliberate `origin=reader`
  prerequisites.

## Known contract drift

The generated same-path contract currently includes
`GET /api/v1/issues/{issue_id}/dependencies`, but the mounted native read is
`GET /api/v2/issues/{issue_id}/dependencies` and the frontend uses v2. Treat the
v1 generated alias as a contract-repair handoff, not a supported route.

## Validation

```sh
cargo run --locked -p comicpile-roll-service --example same_path_openapi \
  > native/contracts/same-path-runtime.openapi.json
node scripts/export_openapi_schema.mjs
node scripts/generate_openapi_types.mjs --check
```

Rust drift tests compare the checked-in same-path document with current DTOs.
There is no `tests/test_api_v1_canonical_contract.py` file at this head; do not
claim that deleted test enforces this document.
