# Issue #4836: MIGRATE: creators browser-called routes to Rust v2

> **Superseded implementation note (2026-11-17 owner correction):** The
> same-path `/api/v1` plan below is historical. The browser now calls the
> canonical Rust-backed `/api/v2/creators*` resources, and the legacy
> `/api/v1/creators*` handlers, native aliases and ingress exceptions have been
> retired. The authoritative contract is `native/contracts/v2-runtime.openapi.json`
> and `native/roll-service/src/creators_v2.rs`; the retired v1 URLs fall through
> to Rust's JSON 404.

## Owner Objective

This issue is **COMPLETE**. All 11 browser-called creators routes were migrated from Python FastAPI to native Rust.

### Summary

- **Migration completed**: All 11 browser-called creators operations serve from Rust-native `/api/v2/creators*` resources
- **Python handler deleted**: `app/api/creators.py` removed; no v1 creators routes in Python
- **Frontend updated**: All 6 frontend services now call `/api/v2/creators*` endpoints
- **Routes registered**: All 11 v2 routes registered in `api/native_roll.rs` (lines 662-687)
- **Inventory updated**: `docs/api/v2-route-inventory.json` shows all 11 operations as `native-rust`
- **Tests updated**: `tests/test_vercel_deployment.py` and `tests/test_shadowed_python_retirement.py` updated

### Current State

- **Python handler**: DELETED (`app/api/creators.py` removed)
- **Frontend callers**: 6 frontend services (api-creators.ts, creatorsApi.ts, creatorComparisonApi.ts, creatorDiscoveryApi.ts, creatorMetricDrilldownApi.ts, creatorTeamChemistryApi.ts)
- **Ingress destination**: All routes served by `/api/native_roll.rs`
- **Native status**: All 11 routes successfully implemented in Rust

## Original Scope (Historical Reference)

All browser-called operations that were migrated (re-derive from docs/api/v2-route-inventory.json):

1. `GET /api/v2/creators` - list creators
2. `GET /api/v2/creators/summaries` - summarize creators
3. `GET /api/v2/creators/compare` - compare creators
4. `GET /api/v2/creators/discoveries` - discover creators
5. `GET /api/v2/creators/team-chemistry` - team chemistry
6. `GET /api/v2/creators/{creator_key}` - creator detail
7. `GET /api/v2/creators/{creator_key}/series/{series_key}/issues` - series issues
8. `GET /api/v2/creators/{creator_key}/metrics/{metric_type}` - metric types
9. `GET /api/v2/creators/{creator_key}/metrics/rating-distribution/{rating_value}` - rating distribution
10. `GET /api/v2/creators/{creator_key}/metrics/role-stats/{role}` - role stats
11. `GET /api/v2/creators/{creator_key}/metrics/series-stats/{series_key}` - series stats

## Retention Note (Owner Direction)

**Per owner correction (2026-11-17)**: The same-path `/api/v1` plan is historical. The browser now calls the canonical Rust-backed `/api/v2/creators*` resources, and the legacy `/api/v1/creators*` handlers have been retired via the catch-all route. No v1 creators paths should be restored as Python routes.

## Acceptance Criteria (Verified Complete)

- [x] All 11 browser-called creators routes served by native Rust (`/api/native_roll.rs`)
- [x] Wire contract preserved: OpenAPI response matches original Python response
- [x] `docs/api/v2-route-inventory.json` updated with all 11 operations as `native-rust`
- [x] Python handler `app/api/creators.py` deleted
- [x] All frontend services updated to use `/api/v2/creators*` paths
- [x] Tests updated to verify route mappings
