# Frontend OpenAPI type boundary

ComicPile generates `frontend/src/generated/openapi.ts` from FastAPI's OpenAPI schema and treats that file as a transport-contract source, not as a replacement for frontend domain and view-model types.

## Use generated transport types when the shapes are exact

The public `frontend/src/types.ts` barrel aliases generated schemas when the frontend contract is structurally identical to the API contract. Current generated aliases cover authentication responses, compatible thread mutations, dependency responses, issue-dependency responses, and bug-report responses.

The post-#921 audit found three remaining exact public duplicates and moved them to generated aliases:

- `IssueDependencyEdge` uses the generated `IssueDependencyEdge` schema.
- `IssueDependenciesResponse` uses the generated `IssueDependenciesResponse` schema.
- `BugReportResponse` uses the generated `BugReportResponse` schema.

Compile-time Vitest contract tests keep these aliases, plus the previously migrated aliases, identical to generated schemas.

## Keep frontend-owned shapes handwritten when they are intentionally different

The following public types remain handwritten because they are projections, ergonomic request shapes, or otherwise not exact OpenAPI schema duplicates:

- `ThreadListItem`, `Thread`, and `ThreadListResponse`: frontend list/detail projections intentionally differ from `QueueThreadListItem`, `ThreadResponse`, and `QueueThreadListResponse` optionality and fields.
- `ThreadQueryParams`: query-string state, not a JSON request schema.
- `ThreadCreatePayload`: the UI does not expose all `ThreadCreate` transport fields.
- `MoveToPositionPayload`: combines the resource id with the position used to build the URL/body request.
- `RatePayload`: contains frontend mutation context beyond the backend `RateRequest` body.
- `UndoPayload`: combines URL/session context with snapshot selection.
- `SessionThread`, `SessionCurrent`, `SessionSummary`, `SessionEvent`, `SessionSnapshot`, `SessionSnapshotsResponse`, and `SessionDetails`: screen/session projections do not exactly match the generated session schemas.
- `AnalyticsSession`, `TopRatedThread`, and `AnalyticsMetrics`: frontend analytics models without exact generated schema equivalents.
- `BlockingInfoResponse`: a focused projection of blocking reasons rather than the complete generated blocking explanation.
- `DependencyCreatePayload`: uses frontend-friendly camel-case discriminator/id fields and is translated at the API boundary.
- `ConnectedThreadInfo` and `ConnectedDependenciesResponse`: the frontend narrows connection type semantics beyond the generated string contract.
- `FlowchartNode`, `FlowchartEdge`, `FlowchartDependency`, and `GraphLayout`: layout/view models, not transport contracts.
- `RollResponse`: the current frontend contract has stricter required nullable fields plus UI context not represented identically by the generated response.

When one of these contracts becomes exactly equivalent to a generated schema, migrate the public barrel export and add a compile-time equality test instead of copying the schema by hand.

## Derived view models keep the generated authority

Some UI contracts are deliberately narrower than the wire schema. They must be
written as aliases derived from the generated component-schema map, not as
standalone `interface`/object-literal copies, so schema drift is still
mechanically visible:

```ts
type GeneratedSchemas = components['schemas']

export type Issue = Omit<GeneratedSchemas['IssueResponse'], 'status' | 'position'> & {
  status: 'unread' | 'read'
  position?: number
}
```

`Issue` and `IssueListResponse` use this pattern (#4457): the generated
`IssueResponse` stays the authority for every transport field, while the alias
applies the two presentation normalizations the reader UI needs (narrowed
`status`, optional `position`) and keeps `next_page_token` required because the
pagination consumers read it unconditionally and the handler always serializes it.

## Duplicate-authority guard

`tests/test_frontend_server_contract_types.py` fails when a new handwritten
`export interface` or inline `export type ... = {` reuses a generated component
schema name. Known pre-#4457 duplicates are frozen in
`tests/frontend_server_contract_types_baseline.json`, which is shrink-only: the
guard also fails when a baseline entry stops existing, so the inventory must be
removed as each type migrates. Regenerate nothing here — migrate the type to a
generated alias and delete its baseline entry.

## Generated request-method decision

ComicPile should not adopt a generated HTTP client as part of the type-generation work. The existing API service owns authentication refresh, CSRF handling, retries, compatibility routes, and frontend-specific request composition. Replacing that behavior with generated request methods would be a separate client-architecture change, not a bounded type-safety improvement. If that migration is ever desired, track it as its own issue with explicit auth/retry compatibility requirements.

## Regeneration

Use the repository's existing OpenAPI generation and stale-artifact checks. Never edit `frontend/src/generated/openapi.ts` directly. Backend schema changes should regenerate the artifact, and generated aliases should make incompatible transport drift visible through frontend type checking.

The generated schema now covers the deployed native Rust `/api/v2` operations as
well as the Python/FastAPI routes. `scripts/export_openapi_schema.py` merges the
Rust-generated `native/contracts/v2-runtime.openapi.json` into `app.openapi()`;
a differing native component name is published as `Native<Name>` so a native
operation never silently references a same-named Python schema. The same run
also emits `frontend/src/generated/nativeV2Client.ts`, a thin typed request
client generated from the native operation set and the merged operation types.
It delegates every call to the existing `HttpClient`; it is not a new transport
and does not change authentication, CSRF, retry or error semantics. Regenerate
all three sources together:

```sh
cd native/roll-service && cargo run --example v2_openapi > ../contracts/v2-runtime.openapi.json
cd ../.. && python scripts/generate_openapi_types.py
```

`scripts/generate_openapi_types.py --check` verifies the schema, `openapi.ts`,
and `nativeV2Client.ts` without overwriting repository artifacts. Custom
`--schema`/`--output` runs do not touch the checked-in native client.

`docs/api/v2-route-inventory.json` and
`tests/test_api_v2_contract_inventory.py` record and enforce which runtime
serves each live `/api/v2` operation.
