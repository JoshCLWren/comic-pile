# Issue #4836: MIGRATE: creators browser-called routes to Rust v2

## Owner Objective

Move all 11 browser-called creators routes from Python FastAPI to native Rust while preserving the exact HTTP method/path contract, OpenAPI response, authentication/ownership checks, SQL/bind/transaction semantics, and query-param/pagination handling. This is a closure-critical cutover that must be proven in production before deleting Python handlers.

## Current State

- **Parent issue**: #4335 (Rust cutover framework)
- **Traffic rank**: 5/11
- **API family**: creators browser-called operations
- **Python handler**: `app/api/creators.py` (/api/v1/creators)
- **Frontend callers**: 6 frontend services (api-creators.ts, creatorsApi.ts, creatorComparisonApi.ts, creatorDiscoveryApi.ts, creatorMetricDrilldownApi.ts, creatorTeamChemistryApi.ts)
- **Ingress destination**: /api/index.py (Python FastAPI catch-all)
- **Native status**: No Rust handler exists for these exact METHOD path pairs yet

## Scope

All browser-called operations in this family (re-derive from docs/api/v2-route-inventory.json at implementation start):

1. `GET /api/v1/creators`
2. `GET /api/v1/creators/compare`
3. `GET /api/v1/creators/discoveries`
4. `GET /api/v1/creators/summaries`
5. `GET /api/v1/creators/team-chemistry`
6. `GET /api/v1/creators/{creator_key}`
7. `GET /api/v1/creators/{creator_key}/metrics/rating-distribution/{rating_value}`
8. `GET /api/v1/creators/{creator_key}/metrics/role-stats/{role}`
9. `GET /api/v1/creators/{creator_key}/metrics/series-stats/{series_key}`
10. `GET /api/v1/creators/{creator_key}/metrics/{metric_type}`
11. `GET /api/v1/creators/{creator_key}/series/{series_key}/issues`

## Implementation Steps

### Phase 1: Rust Implementation

1. **Create Rust handlers in `/api/native_creators.rs`**:
   - Implement all 11 route handlers using Axum
   - Preserve exact HTTP method and path (same-path migration)
   - Implement authentication and authorization checks
   - Implement SQL query construction and execution
   - Preserve query-param handling, pagination, and drilldown metric types
   - Ensure no N+1 queries or per-row fan-out

2. **Register routes in `app/router_mounts.py`**:
   - Add mount entries for the new Rust handlers
   - Use same path prefixes as Python handlers

3. **Generate OpenAPI schema**:
   - Run `uv run --frozen python scripts/export_openapi_schema.py`
   - Verify generated schema matches Python contract

### Phase 2: Testing

1. **Unit tests**:
   - Create tests in `tests/test_creators_api.py` (or extend existing)
   - Test success paths for all 11 operations
   - Test error paths (404, 401, validation errors)
   - Test query-param and pagination handling

2. **Integration tests**:
   - Use existing `tests/conftest.py` fixtures
   - Test with authenticated user context
   - Verify SQL queries and transactions

3. **Frontend tests**:
   - Run targeted frontend tests for affected services
   - Verify API calls work correctly

### Phase 3: Documentation and Validation

1. **Update route inventory**:
   - Update `docs/api/v2-route-inventory.json`
   - Mark operations as `native-rust` with cutover owner
   - Regenerate burndown table via `python3 scripts/generate_route_burndown.py`

2. **Runtime proof**:
   - Verify authenticated production requests execute in Rust
   - Check ingress logs and runtime evidence
   - Ensure no Python execution for these paths

### Phase 4: Cleanup

1. **Delete Python handler**:
   - Remove `app/api/creators.py`
   - Remove mount entries from `app/router_mounts.py`
   - Delete any Python-exclusive service/repository/schema/test helpers

2. **Verify shared code**:
   - Ensure no code still shared by other operations is removed
   - Run full test suite to catch any regressions

## Verification Commands

```bash
# Backend validation
ruff check .
ty check --error-on-warning
bash scripts/check-python-ci-lint.sh
pytest tests/test_creators_api.py -v

# Frontend validation
cd frontend && pnpm run lint && pnpm run typecheck
cd frontend && pnpm exec vitest run <affected-test-files>

# OpenAPI generation
uv run --frozen python scripts/export_openapi_schema.py --check

# Route generation
python3 scripts/generate_route_burndown.py --check
```

## Rollback Strategy

- Keep Python handler in place until Rust implementation is proven in production
- Use feature flag or dual-path if needed for gradual rollout
- Preserve rollback to Python path if critical issues arise

## Risk Mitigation

- Read-only family (no writes) - lower risk
- Preserve exact wire contract to avoid breaking frontend
- Comprehensive test coverage to catch regressions
- Runtime proof requirement ensures actual Rust execution

## Acceptance Criteria (Done when - all must hold)

- [ ] Move **every browser-called /api/v1/* and /api/* operation above to native Rust same-path**: same HTTP method and exact path (including both the /api/* and /api/v1/* twins where the family has them) served by the native binary (/api/native_roll.rs or /api/native_issue.rs via vercel.json). Front-end URLs stay unchanged. Never redirect /api/v1/* to /api/v2/* as a shortcut.
- [ ] Preserve the wire contract: generated native OpenAPI response matches the Python response (status codes, types, required/optional fields, colon-action suffixes, trailing-slash behavior, error shapes), plus auth/ownership checks, SQL/bind/transaction semantics, and SQL budgets (no N+1, no per-row fan-out regressions).
- [ ] Update docs/api/v2-route-inventory.json (runtime + native contract) and regenerate any burndown/AGENTS.md table via scripts/generate_route_burndown.py in the cutover PR.
- [ ] **Prove an authenticated production request ran in Rust**: show a real authenticated production request for every operation above executing in the Rust binary (runtime evidence from deployed ingress/logs, not just health/401/READY or deployed code). Each METHOD path must have production evidence or an explicit, reviewer-approved reason why one representative proves its siblings.
- [ ] **Then delete the Python handler**: after proof, delete the Python handler, its mount entries in app/router_mounts.py, and any now-dead Python service/repository/schema/test helpers exclusive to it. Do not delete code still shared by other operations.
- [ ] Exact-head green required CI and independent exact-head semantic/acceptance review. Greptile is optional; any actionable Greptile finding needs a fix or concrete evidence rebuttal.
