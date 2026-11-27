# Retained `/api/v1` API Surface

> **Status: archival compatibility catalogue.** Retained `/api/v1` paths are
> native Rust compatibility operations kept only for callers that have not been
> migrated yet. They are **not** permission for new v1 consumers and they are
> **not** the current client contract. Use [API.md](API.md), the generated
> native/same-path contracts, and [the route inventory](api/v2-route-inventory.json)
> for the contract to code against.
<!-- docs-path-check: historical -->

This document supports the `/api/v1` normalization audit (#642, #954) and the
Rust v2-only end state in #4335 / #4456. It records the retained v1 surface; it
does not authorize new v1 work. Per-route retirement is owned by #5719 (live
inventory) and the small migration slices #5701–#5718.

## Current runtime

The Python application runtime is retired; there is no Python handler, process,
module, or deployed function behind any `/api/v1` path. Every remaining v1
operation is served by the native Rust ingress `api/native_roll.rs`
(`vercel.json` routes `/api(?:/.*)?` to it). There is no Python-runtime
exception, parity oracle, or "Python stays mounted" hold on this surface.

There are 22 retained `/api/v1` operations, all served by native Rust, in three
groups:

| Group | Retained v1 operations | Target v2 resource |
|-------|------------------------|--------------------|
| Stateless previews | 3 (`POST /api/v1/catalog/series-mappings/preview`, `POST /api/v1/continuity-plans/{plan_id}/reading-orders/project-preview`, `POST /api/v1/issue-identity/cbl/{list_id}/reading-graph-preview`) | stateless v2 preview operations (#5714, #5715, #5716) |
| Reading-order groups | 7 (`/api/v1/reading-order-groups…` collection list/create, item GET/PATCH/DELETE, detail, order) | `/api/v2/readingOrderGroups…` and memberships/ranges (#5710, #5711) |
| Threads | 12 (`/api/v1/threads…` create, check-duplicates, excluded, reactivate, stale, item PUT/DELETE, exclude, restore, set-pending, test-backdate, issues/creators) | `GET/POST/PATCH/DELETE /api/v2/threads…` (#5701, #5703, #5704, #5705, #5706) |

The five thread dependency-diagnostic v1 operations (`GET /api/v1/threads/{id}/issue-dependencies`, `GET /api/v1/threads/{id}/dependencies`, `POST /api/v1/threads/{id}:getBlockingInfo`, `POST /api/v1/threads:getBlockingInfo`, `GET /api/v1/threads/{id}/connected`) were retired with the v2 thread diagnostics resources in #5709 and are no longer retained surface.

`docs/api/v2-route-inventory.json` is authoritative for the exact
`METHOD path` list and its caller lists. `scripts/check_v1_canonical_guidance.mjs`
fails CI when the count above and the inventory disagree, when any retained v1
operation is attributed to a non-Rust runtime, or when active guidance starts
telling new code to use v1 again.

The v1 count is **not** the v2 retirement proof: the v2 inventory counts v2
operations only. Retiring a v1 route requires its callers to move to the v2
resource, the route to be removed from the Rust router and route fragments, and
the obsolete path to 404 in production.

## What new client code must use

New frontend, background and recovery callers use the canonical v2 resources
(AIP-121/122/131–136/185): `GET /api/v2/threads` and
`GET /api/v2/threads/{thread_id}` for Thread reads, the
`/api/v2/readingOrderGroups…` family for reading-order groups, the stateless v2
preview operations for the three preview paths above, and the per-family v2
resources listed in [API.md](API.md). Do not add a caller to a retained
`/api/v1` path, do not re-add a retired v1 path as an alias, and do not mirror a
v2 resource back onto v1 "for symmetry".

## Retired families (not surface)

These v1 and unversioned families are gone, not merely deprecated. They have no
handler, no supported route, and no compatibility alias:

- Auth (`/api/v1/auth`, `/api/auth`) — the product client uses `/api/v2/auth/*`.
- Analytics (`/api/v1/analytics/metrics`, `/api/analytics/metrics`) — replaced by
  the bounded native `GET /api/v2/analytics/metrics`.
- Continuity, continuity-plans, continuity-rules, dependencies, issues, queue,
  rate, releases, roll, sessions, and undo v1 families — migrated to their v2
  resources under #4335 / #4456.
- Snooze (`POST /api/v1/snooze/`, `POST /api/v1/snooze/{id}/unsnooze`, legacy
  `/api/snooze`) — retired with the Rust roll cutover (#4338, #4349). Snooze is
  the native `POST /api/v2/roll/offer` reroll; unsnooze is client-only (the
  `comicpile_roll_snoozes` browser cookie) and has no server route.
- The 16 unversioned `threads`, `sessions` and `undo` operations — retired after
  a caller audit. No unversioned operations remain in the live inventory.

## Intentional bare `/api` compatibility routes

Two categories of bare `/api/<segment>` routes are retained deliberately:

1. **Native compatibility aliases** — `GET /api/threads/{thread_id}`,
   `GET /api/sessions/{session_id}`, `GET /api/sessions/{session_id}/snapshots`,
   plus the Roll and auth compatibility aliases. They are served by native Rust
   and are excluded from the versioned inventory count. They are retained for
   existing callers only; new code uses the v2 resource.
2. **Infrastructure surfaces** — bounded health, ping and metrics routes remain
   available. Retired admin, debug and bug-report aliases are not exceptions.

Any other bare `/api` route is a regression and fails
`python3 scripts/check_route_fragment_guard.py`.

## Collections

Collections were removed. The OpenAPI document contains no supported Collections
route, schema, or operation. Durable reader exclusions under Option E remain in
storage, but the distinct `/api/v1/collection-exclusions` HTTP API was retired
with the Python API (part of #5431). References to a *retired* `collection_id`
query parameter in legacy operation descriptions document removed behavior; they
are not supported surface.

## Verification

These are the checks that actually exist and run:

```bash
node scripts/check_v1_canonical_guidance.mjs   # this catalogue vs live inventory, no v1 instructions
python3 scripts/check_route_fragment_guard.py  # route fragments only; generated outputs stay bot-owned
node scripts/generate_openapi_types.mjs --check # generated OpenAPI schema, types and native client
python3 scripts/check_markdown_docs.py         # Markdown policy
```

The former `tests/test_api_v1_canonical_contract.py` contract test no longer
exists (the Python test tree it lived in was retired), so this document must not
claim it as enforcement.
