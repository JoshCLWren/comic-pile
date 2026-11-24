# Native API contracts

ComicPile's checked-in OpenAPI documents are generated from Rust `serde` /
`utoipa` DTOs. They are transport contracts, not hand-maintained route tables.
The Vercel ingress and frontend service callers must agree with the generated
operation set.

## Canonical documents

- [`v2-runtime.openapi.json`](v2-runtime.openapi.json) is the aggregate native
  v2 contract produced by `comicpile_roll_service::openapi::canonical_openapi`.
- [`same-path-runtime.openapi.json`](same-path-runtime.openapi.json) preserves
  operations that intentionally keep their original v1 or unversioned HTTP
  method/path while running in Rust. A v1 URL is not evidence of a Python
  runtime.
- [`python-legacy.openapi.json`](python-legacy.openapi.json) is a frozen wire
  snapshot used only to preserve contracts for retired Python operations. No
  Python handler is deployed.
- [`frontend/src/generated/openapi.json`](../../frontend/src/generated/openapi.json)
  and [`openapi.ts`](../../frontend/src/generated/openapi.ts) are the merged
  client-facing schema and types. `nativeV2Client.ts` is generated from the
  native operation set and delegates to the existing frontend `HttpClient`.

The per-domain artifacts (for example `issue-v2`, `threads-v2`, `preferences-v1`
and `bug-reports-v1`) are focused generated contracts with their own Rust drift
tests. `roll-bootstrap-v1.openapi.json` and its SQL oracle transcript are frozen
historical comparison evidence from the retired Python bootstrap handler; they
are not live runtime contracts.

## Regeneration

Run from the repository root:

```sh
cargo run --locked -p comicpile-roll-service --example v2_openapi \
  > native/contracts/v2-runtime.openapi.json
cargo run --locked -p comicpile-roll-service --example same_path_openapi \
  > native/contracts/same-path-runtime.openapi.json
node scripts/export_openapi_schema.mjs
node scripts/generate_openapi_types.mjs
```

Use the non-writing drift check after regeneration:

```sh
node scripts/generate_openapi_types.mjs --check
```

Rust tests compare the checked-in aggregate and same-path documents with the
current DTO declarations. Frontend CI also verifies generated-contract
freshness. Do not edit generated JSON or TypeScript directly.

## Runtime and caller evidence

[`docs/api/v2-route-inventory.json`](../../docs/api/v2-route-inventory.json) is
the generated v2 cutover inventory. Its `full_surface` section describes the
retired Python-handler surface and fragment-owned v1 operations; it is not an
exhaustive list of every native v1 compatibility route. For retained same-path
operations, use `same-path-runtime.openapi.json`, the route registry in
[`native/roll-service/src/lib.rs`](../../native/roll-service/src/lib.rs), and
the frontend service callers together.

See [API documentation](../../docs/API.md) for the versioning and ingress rules.
