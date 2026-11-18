# Issue #4832 Threads Browser-Routes Rust Migration Progress

## Owner correction priorities (2026-11-17)
1. `POST /api/v1/threads/groups:batch`
2. `GET /api/v1/threads/excluded/threads`
3. `GET /api/v1/threads/{thread_id}/connected`
4. `GET /api/v1/threads/{thread_id}/issues/creators`

## Actions completed
- Derived live route list from `docs/api/v2-route-inventory.json` full_surface.
- Updated route fragments to route priority operations to native Rust:
  - `docs/api/route-fragments/threads.json`
    - `/api/v1/threads/excluded/threads` dest → `/api/native_roll.rs`
    - `/api/v1/threads/groups:batch` dest → `/api/native_roll.rs`
    - `/api/v1/threads/{thread_id}/connected` dest → `/api/native_roll.rs`
  - `docs/api/route-fragments/creators.json`
    - `/api/v1/threads/{thread_id}/issues/creators` dest → `/api/native_roll.rs`
- Added Rust module `native/roll-service/src/threads_extra.rs` with stub handlers preserving signatures.
- Registered module in `native/roll-service/src/lib.rs` and added Axum routes:
  - `POST /api/v1/threads/groups:batch` → `threads_extra::list_thread_groups_batch`
  - `GET /api/v1/threads/excluded/threads` → `threads_extra::list_excluded_threads`
  - `GET /api/v1/threads/{thread_id}/connected` → `threads_extra::get_thread_connected`
  - `GET /api/v1/threads/{thread_id}/issues/creators` → `threads_extra::get_thread_issue_creators`

## Remaining work for closure-critical acceptance
- Implement full wire-contract logic in `threads_extra.rs`:
  - Auth + ownership checks matching Python `dependency_group_service.list_thread_groups_batch`
  - Bounded SQL, no N+1, same response shape `dict[int, list[DependencyGroupSummary]]`
  - Preserve pagination / error shapes for excluded threads, connected threads, creators
- Add focused Rust unit tests for each handler and request-count regression tests.
- Update `docs/api/v2-route-inventory.json` runtime to `native-rust` after proof.
- Verify production authenticated Rust execution for each METHOD/path.
- Delete Python handlers `app/api/dependency_group_batch.py`, related mounts, and dead service helpers after proof.
- Exact-head CI green + independent exact-head semantic/acceptance review.

## Notes
- No commits/push performed per wrapper constraints.
- Route fragments are bot-owned; vercel.json will regenerate on merge.
- Stubs return empty payloads; do not deploy without full implementation.
