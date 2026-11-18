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

## remaining work for closure-critical acceptance
- Implement full wire-contract logic in `threads_extra.rs`:
  - Auth + ownership checks matching Python `dependency_group_service.list_thread_groups_batch`
  - Bounded SQL, no N+1, same response shape `dict[int, list[DependencyGroupSummary]]`
  - Preserve pagination / error shapes for excluded threads, connected threads, creators
- Add focused Rust unit tests for each handler and request-count regression tests.
- Update `docs/api/v2-route-inventory.json` runtime to `native-rust` after proof.
- Verify production authenticated Rust execution for each METHOD/path.
- Delete Python handlers `app/api/dependency_group_batch.py`, related mounts, and dead service helpers after proof.
- Exact-head CI green + independent exact-head semantic/acceptance review.

## Acceptance criteria status (A1-A74)
- **Migrated to native Rust same-path** (verified via route fragments):
  - A41: GET /api/v1/threads/excluded/threads → native-rust (route fragment dest = /api/native_roll.rs)
  - A42: POST /api/v1/threads/groups:batch → native-rust (route fragment dest = /api/native_roll.rs)
  - A48: GET /api/v1/threads/{thread_id}/connected → native-rust (route fragment dest = /api/native_roll.rs)
  - A55: GET /api/v1/threads/{thread_id}/issues/creators → native-rust (route fragment dest = /api/native_roll.rs)
- **Still Python** (route fragment dest = /api/index.py):
  - A36: POST /api/v1/threads/
  - A37: GET /api/v1/threads/active
  - A38: POST /api/v1/threads/check-duplicates
  - A39: GET /api/v1/threads/completed
  - A40: GET /api/v1/threads/completed/threads
  - A43: POST /api/v1/threads/reactivate
  - A44: GET /api/v1/threads/stale
  - A45: DELETE /api/v1/threads/{thread_id}
  - A46: GET /api/v1/threads/{thread_id}
  - A47: PUT /api/v1/threads/{thread_id}
  - A51: POST /api/v1/threads/{thread_id}/exclude
  - A52: GET /api/v1/threads/{thread_id}/issue-dependencies
  - A53: GET /api/v1/threads/{thread_id}/issues
  - A54: POST /api/v1/threads/{thread_id}/issues
  - A56: POST /api/v1/threads/{thread_id}/issues/{issue_id}/attach-external
  - A57: POST /api/v1/threads/{thread_id}/issues:reorder
  - A58: GET /api/v1/threads/{thread_id}/issues:validateOrder
  - A59: GET /api/v1/threads/{thread_id}/reading-orders
  - A60: POST /api/v1/threads/{thread_id}/restore
  - A61: POST /api/v1/threads/{thread_id}/series/{series_external_id}/attach
  - A62: POST /api/v1/threads/{thread_id}/set-pending
  - A63: PUT /api/v1/threads/{thread_id}/test-backdate
  - A64: POST /api/v1/threads/{thread_id}:getBlockingInfo
  - A65: POST /api/v1/threads/{thread_id}:migrateToIssues
  - A66: POST /api/v1/threads/{thread_id}:migrateToIssuesSimple
  - A67: POST /api/v1/threads/{thread_id}:setCurrentIssue
  - A68: POST /api/v1/threads:getBlockingInfo
- **A70 (wire contract)**: Stub handlers return empty payloads; full implementation needed for production parity
- **A71 (inventory update)**: Route fragments are bot-owned; regenerate via `scripts/generate_route_burndown.py` after code changes
- **A72 (production Rust execution)**: Stubs registered but return empty payloads; not yet verified for authenticated production execution
- **A73 (delete Python handlers)**: Python handlers remain in `app/api/thread.py` and `app/api/dependency_group_batch.py`; deletion after proof
- **A74 (CI + review)**: Pending exact-head green CI and independent semantic/acceptance review

## Notes
- Route fragments are bot-owned; vercel.json will regenerate on merge via `.github/workflows/regenerate-routes.yml`
- Stubs return empty payloads; full implementation required for production deployment
- This checkpoint does not commit or push per wrapper constraints