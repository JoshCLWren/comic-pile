# Rate Limiting

Comic Pile protects authentication and outbound-provider paths. There is no
global SlowAPI/FastAPI middleware; the retired Python application was removed
in the Rust cutover, and the limits below live in the native Rust service.

## Authentication endpoints

`native/roll-service/src/auth/handlers.rs` keeps a process-local limiter for
authentication requests:

- Keys are endpoint-scoped client IPs, or token digests for refresh requests —
  never usernames, passwords, or raw secrets.
- The limiter map is bounded (`MAX_RATE_LIMIT_KEYS`, 4096 entries) and evicts
  keys with no attempt inside a one-hour retention window, so rotating
  attacker-controlled keys cannot grow memory without bound.
- Refresh is limited per token digest (20 attempts per 60-second window).
- Exceeding a limit returns `429 Too Many Requests`; if pressure eviction has to
  clear the map, the database-backed lockout remains authoritative.

## Login lockout

Failed logins are also recorded in PostgreSQL (`failed_login_attempts`) and
checked per username and per client IP under advisory locks. This durable
lockout — not the in-process limiter — is authoritative and survives process
restarts. A successful login clears the username's failure row; password reset
changes credentials and the credential epoch but does not itself delete all
username/IP lockout rows.

## Outbound GitHub issue filing

Bug-report submissions share a rate limit on creating GitHub issues. When the
budget is exhausted the API returns `429` with a `Retry-After` interval and a
reset time in the response detail; it does not queue or silently drop the
report.

## ComicVine provider limits

ComicVine repair defines its own provider backoff
(`native/roll-service/src/comicvine_repair.rs`):

- HTTP 420/429 responses are treated as provider rate limiting.
- The work item becomes `deferred` with a bounded `retry_after` (local backoff,
  capped at one hour).
- After repeated failures (three attempts) the item is marked `failed` with a
  six-hour retry window instead of retrying indefinitely.

## Client guidance

- Honor `429` and `Retry-After`; do not hot-loop on refresh or login.
- Do not retry a failed login immediately; wait for the lockout window.
- Batch reads and use cursor pagination (`page_size`, `page_token`) instead of
  polling full collections.

## Testing

- Rust auth tests cover limiter behavior and the 429 path:
  `cargo test -p comicpile-roll-service auth`.
- Browser suites run with test-only configuration that disables limits so
  fixtures can register users at test speed (`.env.test`,
  `ENABLE_RATE_LIMITING_IN_TESTS=false`).
- Do not weaken or bypass a limit to make a test pass; fix the test setup
  instead.
