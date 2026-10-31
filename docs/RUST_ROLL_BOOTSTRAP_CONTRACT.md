# GET /api/v2/roll/bootstrap: native Rust contract

> **API v2 is a URL contract, not a language.** The only supported Roll
> bootstrap operation is `GET /api/v2/roll/bootstrap`, and it is implemented
> by native Rust ingress (`api/native_roll.rs` → `native/roll-service`).
> `vercel.json` routes that method/path to the Rust function; FastAPI exposes
> no bootstrap handler. `GET /api/v1/roll/bootstrap` and
> `GET /api/roll/bootstrap` are retired and return no application route. The
> Python v1, legacy and v2 handlers were deleted in #4397 after both live
> clients moved to v2 (#4383).

## Frozen contracts

- `native/contracts/roll-bootstrap-v2.openapi.json` is the frozen OpenAPI
  operation and transitive component closure for the supported v2 operation.
  It was captured with `scripts/rust_endpoint_oracle.py` from the
  Python-generated client schema immediately before the Python handler was
  deleted, so it still describes the wire contract the Rust implementation
  must satisfy.
- `native/contracts/roll-bootstrap-v1.openapi.json` is the historical v1
  operation snapshot retained as behavioral evidence (#4371). It is **not** an
  implementation mandate: v1 is retired, not ported.
- `app/schemas/roll_v2.py` is the frozen Python DTO.
  `tests/test_roll_v2_frozen_contract.py` keeps its field set aligned with the
  frozen v2 contract and guards the Roll UI visibility fields.

The v2 contract deliberately extends the original v2 response with the data
the live Roll screen needs, so no Python v1 enrichment call or fallback is
required:

- candidate `thread.tags` on every rollable item and summary row;
- `total_threads`, `available_threads`, `excluded_count`, `excluded_threads`,
  `inactive_count` and a reachable `inactive_threads` list;
- blocked, snoozed, skipped and stale summaries and counts;
- issue id/number, route labels, reader context, session/die/timezone,
  recovery, pending and last-read behavior.

## Behavior oracle and verification

The Rust implementation is authoritative. Its behavior is checked by:

```sh
cd native/roll-service
cargo fmt --all --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked --all-targets
```

The authenticated HTTP parity test runs against isolated PostgreSQL tables:

```sh
uv run pytest native/roll-service/parity/ -q -s --no-cov
```

`native/roll-service/parity/test_http_bootstrap.py` seeds an owned library and
asserts the native response includes candidate tags, exact issue identity,
route labels, the inactive drill-down, stale selection, recovery and session
writes. `frontend/src/unit/adaptRollV2Bootstrap.test.ts` rejects native rows
without visible tags and preserves the inactive/excluded UI data.

To compare a separately generated native OpenAPI operation with the frozen
v2 contract:

```sh
python scripts/rust_endpoint_oracle.py check \
  --schema /tmp/rust-generated-openapi.json \
  --contract native/contracts/roll-bootstrap-v2.openapi.json \
  --path /api/v2/roll/bootstrap
```

The comparison includes the full referenced component closure, not only the
top-level response. A frozen Python file alone does not prove native parity,
runtime behavior or a production cutover.

## Request flow and side effects

The native handler authenticates a bearer access token, resolves the owner's
recent unended reading session (preferring pending work), initializes missing
bandwidth once, captures the browser timezone once when unset, and returns the
validated projection. GET can create reading history, initialize bandwidth,
capture timezone and write a session-start undo snapshot. It does not
rate/read an issue, roll/select a new target, change queue positions, rotate
refresh credentials or emit a reading Event.

Auth failure occurs before reading-history bootstrap. HTTP 422 validation
remains in the contract; an invalid timezone is ignored rather than rejected.
Dependency outages use the application's stable 503 boundary; unforeseen
failures use its 500 handler. Cyclic or missing-reference Option E inputs fail
closed rather than returning a partial candidate set.

The retired Python bootstrap code must not be reintroduced. Remaining Python
Roll routes are the POST mutations and the v1 exclusion drill-down; the
bootstrap GET is native-only with no fallback or dual serving.
