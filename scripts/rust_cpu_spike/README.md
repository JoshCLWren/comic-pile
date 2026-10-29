# Native Rust CPU experiment (local only)

This is an **authenticated, read-only Roll v2 projection subset**, **not**
a replacement for `GET /api/v2/roll/bootstrap`.

## Scope

`GET /spike/sessions/{session_id}/last-read` executes the same latest-rate
event projection as `app.repositories.roll_v2_projection.fetch_session_last_read`
after validating a locally signed HS256 access JWT, its username, revocation
record and session ownership. It performs three database queries and creates
one connection per request. The Rust server does not initialize Python.

`GET /health` is independent of database access and measures native startup
readiness. No mutations, external API traffic or production configuration are
included.

## Prerequisites

On the Mac, Rust/Cargo, a disposable PostgreSQL database bound to
127.0.0.1:55435, and existing local profile environment variables.

Build first:

```sh
cargo build --manifest-path scripts/rust_cpu_spike/Cargo.toml --release
```

The runner must supply `LOCAL_PROFILE_DATABASE_URL` (strictly host
127.0.0.1, port 55435), `SECRET_KEY` matching its local JWT and
`RUST_SPIKE_PORT`. Do not print or commit these values.

## Correctness and measurement caveats

The projection query is identical in intent, but this endpoint adds explicit
session ownership authorization around a repository function that ordinarily
runs under an already-authenticated service. A parity runner must call the
Python repository function with the **same** (session_id, user_id), compare
canonical JSON, and reject cross-owner access before the CPU experiment can
claim equivalent work.

This subset does not calculate rollable candidates, reading-order
frontiers, exclusions, snoozes, pending roll recovery, mode, manual die,
timezone or Roll bootstrap DTOs. It cannot establish full bootstrap CPU savings.
The three-query request includes new PostgreSQL connection overhead, unlike a
warm SQLAlchemy pool, and this must be accounted for in interpretation.
Local process CPU is not Vercel billed Active CPU.
