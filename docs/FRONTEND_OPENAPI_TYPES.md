# Frontend OpenAPI type boundary

ComicPile generates `frontend/src/generated/openapi.ts` from FastAPI's OpenAPI schema and treats that file as a transport-contract source, not as a replacement for frontend domain and view-model types.

## Use generated transport types when the shapes are exact

The public `frontend/src/types.ts` barrel aliases generated schemas when the frontend contract is structurally identical to the API contract. Current generated aliases cover authentication responses, compatible thread mutations, dependency responses, issue-dependency responses, and bug-report responses.

The post-#921 audit found three remaining exact public duplicates and moved them to generated aliases:

- `IssueDependencyEdge` -> `components['schemas']['IssueDependencyEdge']`
- `IssueDependenciesResponse` -> `components['schemas']['IssueDependenciesResponse']`
- `BugReportResponse` -> `components['schemas']['BugReportResponse']`

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
- `Issue` and `IssueListResponse`: the frontend model intentionally narrows status and omits backend-only position data, so it is not identical to `IssueResponse`/`IssueListResponse`.
- `BlockingInfoResponse`: a focused projection of blocking reasons rather than the complete generated blocking explanation.
- `DependencyCreatePayload`: uses frontend-friendly camel-case discriminator/id fields and is translated at the API boundary.
- `ConnectedThreadInfo` and `ConnectedDependenciesResponse`: the frontend narrows connection type semantics beyond the generated string contract.
- `FlowchartNode`, `FlowchartEdge`, `FlowchartDependency`, and `GraphLayout`: layout/view models, not transport contracts.
- `RollResponse`: the current frontend contract has stricter required nullable fields plus UI context not represented identically by the generated response.

When one of these contracts becomes exactly equivalent to a generated schema, migrate the public barrel export and add a compile-time equality test instead of copying the schema by hand.

## Generated request-method decision

ComicPile should not adopt a generated HTTP client as part of the type-generation work. The existing API service owns authentication refresh, CSRF handling, retries, compatibility routes, and frontend-specific request composition. Replacing that behavior with generated request methods would be a separate client-architecture change, not a bounded type-safety improvement. If that migration is ever desired, track it as its own issue with explicit auth/retry compatibility requirements.

## Regeneration

Use the repository's existing OpenAPI generation and stale-artifact checks. Never edit `frontend/src/generated/openapi.ts` directly. Backend schema changes should regenerate the artifact, and generated aliases should make incompatible transport drift visible through frontend type checking.
