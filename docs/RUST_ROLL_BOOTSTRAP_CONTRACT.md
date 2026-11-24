# `GET /api/v2/roll/bootstrap` behavior contract

`GET /api/v2/roll/bootstrap` is a native Rust **read-only** projection. The v1 and
unversioned bootstrap GET aliases are retired. API version identifies the wire
contract, not the implementation language.

The authoritative schema is `BootstrapResponseV2` in
`native/contracts/v2-runtime.openapi.json`. `frontend/src/types/rollV2.ts` is a
hand-maintained UI projection over that payload, not generated output. Keep its
differences explicit; do not introduce a second wire schema or hand-edit generated
OpenAPI/TypeScript artifacts.

## Sessionless Roll and explicit history initialization

Roll is sessionless at the product boundary (#4405). The bootstrap GET never
creates or mutates a reading-history session, bandwidth, timezone, undo snapshot,
pending offer, die, queue position or Event.

Legacy consumers that need durable history initialization call the separate
write endpoint:

```http
POST /api/v2/reading-sessions
```

It initializes or reuses the appropriate history row and may capture timezone.
The frontend calls it explicitly before the bootstrap read. Direct manual
Read/Rate actions are independent exact-Issue writes and do not depend on this
history initializer.

## Request flow

1. Authenticate the bearer access token, including expiry, JTI, revocation, user
   existence and password-change epoch. Reading-history sessions are not login
   credentials.
2. Resolve existing session context read-only. If no applicable history exists,
   return `404 {"detail":"No active session"}` rather than creating one. The
   frontend handles that 404 by explicitly calling `POST /api/v2/reading-sessions`
   and retrying the bootstrap read.
3. Load and validate the canonical Reading List inputs. Only natural series
   order, current lists/gates/exclusions and explicit `origin=reader`
   prerequisites govern automatic-Roll eligibility. Historical/converted edges
   and cached `is_blocked` flags are not authorities.
4. Derive eligible frontiers, apply durable and browser snooze/skip filters, and
   bound the pool by the current die before loading display metadata.
5. Return rollable Issues, `pool_reason`, pending/recovery context, bandwidth and
   other fields actually declared in `BootstrapResponseV2`.

The owner's 2026-11-23 correction requires one canonical evaluator with no
`OPTION_E_ENABLED` / `OPTION_E_APPROVED_PREVIEW` mode or legacy fallback. The
checked-in mode branches are an implementation discrepancy tracked by
[#3676](https://github.com/JoshCLWren/comic-pile/issues/3676) and
[#5525](https://github.com/JoshCLWren/comic-pile/issues/5525), not supported
configuration.

## Scoped resources

The bootstrap is not the only Roll read:

- `GET /api/v2/roll/die-state` owns selected die and ladder state.
- `GET /api/v2/roll/eligible-issue-ids` owns the bounded eligible ID set.
- `POST /api/v2/issues/cards` enriches the visible Issues in one bounded batch.
- `POST /api/v2/reading-boundaries` returns 1–200 Thread boundary explanations.

The old excluded/inactive/blocked/stale whole-library counters were intentionally
retired from the v2 payload. `pool_reason` explains an empty pool, and route
overflow metadata preserves the visible “+N more” behavior. Do not restore obsolete
counters merely because an old migration document required them.

## Validation

DB-backed bootstrap tests require a disposable database with committed migrations
applied:

```sh
RUST_ROLL_TEST_DATABASE_URL=postgresql://... \
  cargo test --locked -p comicpile-roll-service bootstrap
```

Missing configuration fails instead of skipping. OpenAPI drift and typed UI-field
checks live in `native/roll-service/src/openapi.rs`. Never point tests at
production or a reader's library.

## Historical production proof

Authenticated production native execution was observed on 2026-11-07 through the
real login, `POST /api/v2/reading-sessions`, bootstrap GET and Roll-offer flow.
Responses carried `X-ComicPile-API-Runtime: rust`; no credentials were retained.
That proof establishes the native path at that time, not a fresh probe for every
later deployment.

The Python oracle fixtures and SQL transcript under `tests/fixtures/roll-v2/v1/`
are frozen historical evidence. No Python bootstrap GET exists to regenerate
them, and no current test should treat them as a live runtime oracle.
