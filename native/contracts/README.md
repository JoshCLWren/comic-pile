# Native OpenAPI contracts

The checked-in contracts are generated from Rust `serde`/`utoipa` declarations. No Python application or runtime OpenAPI endpoint exists.

## Canonical generation pipeline

1. `v2-runtime.openapi.json` aggregates declared native `/api/v2/*` operations from the per-domain Rust contracts.
2. `same-path-runtime.openapi.json` describes native operations that intentionally retain v1 or unversioned method/path contracts.
3. `python-legacy.openapi.json` is a frozen compatibility-schema input for retained legacy DTOs. It is not a live Python handler.
4. `scripts/export_openapi_schema.mjs` merges those inputs into `frontend/src/generated/openapi.json`.
5. `scripts/generate_openapi_types.mjs` emits `frontend/src/generated/openapi.ts` and the thin `nativeV2Client.ts` request-method client.

The generated client delegates to the existing `HttpClient`; it does not replace authentication refresh, CSRF, retry, or error handling.

```sh
cargo run --locked -p comicpile-roll-service --example v2_openapi \
  > native/contracts/v2-runtime.openapi.json
cargo run --locked -p comicpile-roll-service --example same_path_openapi \
  > native/contracts/same-path-runtime.openapi.json
node scripts/export_openapi_schema.mjs
node scripts/generate_openapi_types.mjs
node scripts/generate_openapi_types.mjs --check
node scripts/export_openapi_schema.mjs --check
```

Do not hand-edit generated JSON or TypeScript. Rust drift tests and the Node generator tests fail when checked-in artifacts diverge.

## Scope and routing

`v2-runtime.openapi.json` is the aggregate of declared native v2 operations, not a claim that every ingress route has a complete utoipa declaration. `docs/api/v2-route-inventory.json` is the generated operation/caller/ingress inventory; its `full_surface` section also records retained compatibility operations and the native catch-all.

API version is a wire-contract version, not an implementation language. Retained v1 paths are served by native Rust where the router and generated same-path contract publish them. Unknown `/api/*` requests terminate at the Rust JSON 404 fallback in production.

## Domain and historical artifacts

- `issue-v2.openapi.json`, `threads-v2.openapi.json`, `bug-reports-v1.openapi.json`, and `preferences-v1.openapi.json` are domain contract artifacts with their own Rust drift tests.
- `roll-bootstrap-v1.openapi.json` is a frozen historical schema from the retired Python bootstrap operation. It is provenance, not a live oracle.
- The retired Python endpoint-oracle scripts/tests and SQL transcript are historical evidence only. Current verification uses Rust contract tests, Node route/generator tests, and DB-backed HTTP tests.

See `docs/API.md`, `docs/FRONTEND_OPENAPI_TYPES.md`, and `docs/RUST_FACTORY_ENDPOINT_PATTERN.md`.
