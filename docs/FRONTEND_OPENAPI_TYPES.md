# Frontend OpenAPI type boundary

Comic Pile generates frontend transport types from native Rust contracts plus a frozen legacy compatibility-schema input. The generated artifacts are transport authority, not a replacement for frontend-owned domain and view-model types.

## Generated artifacts

- `native/contracts/v2-runtime.openapi.json` — aggregate declared native v2 operations.
- `native/contracts/same-path-runtime.openapi.json` — native operations retaining v1/unversioned paths.
- `native/contracts/python-legacy.openapi.json` — frozen compatibility DTO input; no Python runtime remains.
- `frontend/src/generated/openapi.json` and `openapi.ts` — merged client schema and types.
- `frontend/src/generated/nativeV2Client.ts` — thin typed request methods that delegate to the shared `HttpClient`.

The shared service layer still owns authentication refresh, CSRF, retries, compatibility routes, and frontend-specific request composition. Do not replace `HttpClient` with a generated transport.

## Type ownership

Use generated types directly when the public shape is exact. Keep a handwritten type only when the frontend intentionally narrows, combines, or projects the wire shape, and derive it from generated schemas where possible so drift remains visible. `frontend/src/types.ts` and its compile-time Vitest contract tests are the current alias boundary; avoid copying stale lists of aliases into documentation.

## Regeneration

After changing Rust DTOs or retained same-path operations, regenerate all canonical artifacts together:

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

Never edit generated JSON or TypeScript directly. Rust contract drift tests, `scripts/generate_openapi_types.test.mjs`, route-fragment tests, and frontend type checking provide the current gates.

`docs/api/v2-route-inventory.json` records runtime, consumers, and ingress destinations. When narrative guidance disagrees with the router, generated contract, or real caller, record and repair the discrepancy rather than inventing a route.
