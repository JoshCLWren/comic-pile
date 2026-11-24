# ComicVine runtime mapping and metadata hydration

ComicPile serves issue intelligence from PostgreSQL first. Live ComicVine work is
limited to explicit provider search/import, exact Issue identity confirmation and
bounded metadata hydration. There is no Python hydrator or local SQLite provider
runtime.

## Issue intelligence read

`GET /api/v2/issues/{issue_id}/comicvine` returns the owned Issue's stored
intelligence without waiting for a provider request. A missing mapping or
incomplete metadata remains visible as such; the read does not guess identity
from title, issue number or Thread mapping.

The retained `GET /api/v1/issues/{issue_id}/comicvine` alias calls the same native
handler for existing clients. New clients use v2.

## Exact identity mapping

Use the shared Issue card's **Map comic** / **Change mapping** action. The native
flow is:

1. Search or import a provider volume/roster.
2. Preview exact Issue-number matches and conflicts.
3. Confirm or replace the exact ComicVine Issue ID with ownership, stale-preview,
   conflict and idempotency checks.
4. Commit the mapping and roster metadata in one transaction.

A confirmed series/volume mapping is context, not proof of an Issue identity.
Provider relationship data is informational and cannot create Dependencies or
change automatic-Roll eligibility.

Current endpoints live under `/api/v2/comicvine/*`, including
`identity:confirm`, `identity:replace`, `metadata:refresh`, series import and
issue import. See [API documentation](API.md) and the generated v2 contract.

## Bounded hydration

After a confirmed mapping or metadata-refresh request, native Rust performs
bounded post-commit hydration:

- Stored provider evidence is normalized before any network call.
- Existing populated/deep metadata is preserved.
- Provider work has network timeouts, bounded retries and durable repair leases.
- HTTP 420/429 responses defer work with bounded backoff rather than hot-looping.
- Cross-process deduplication uses PostgreSQL locks/leases; a provider failure
  does not fail Roll, Queue or rating.

The durable metadata store is PostgreSQL. Temporary caches are best-effort only
and must not be treated as application state.

## Configuration and operations

Set `COMICVINE_API_KEY` only in the native service's server-side environment. A
GitHub Actions secret is not automatically injected into Vercel. Never expose
the key to frontend variables, source, logs, screenshots or artifacts.

Authenticated maintenance routes under `/api/v2/maintenance/comicvine-metadata-*`
and the maintained GitHub Actions repair workflow process bounded backlogs. They
are operator tooling, not a candidate-discovery or bulk-remapping shortcut.

## Reader-facing behavior

Every relevant Issue-card surface must render the exact Issue's confirmed
ComicVine CDN artwork or a nonblocking placeholder and keep **Map comic**
available when identity/details are missing. See
[`docs/ISSUE_CARD_MOUNT_INVENTORY.md`](ISSUE_CARD_MOUNT_INVENTORY.md) for the mount
contract.

Historical Python fixtures and hydrator reports remain provenance only. Current
regressions live with the native ComicVine handlers and shared issue-card tests.
