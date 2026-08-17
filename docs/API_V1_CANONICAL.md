# Canonical `/api/v1` API Surface

This document is the authoritative reference for ComicPile's versioned API surface. It
supports issue #638 (Developer experience and frontend simplification) and the
#642 `/api/v1` normalization audit (#954). The companion contract test
`tests/test_api_v1_canonical_contract.py` enforces every statement below against the
generated OpenAPI schema, so this list cannot silently drift.

## Canonical families (must use `/api/v1`)

These retained first-party client families are exposed under `/api/v1/<family>` and are
the supported, documented surface. New client code must call these paths:

| Family | Canonical prefix |
|--------|------------------|
| Analytics | `/api/v1/analytics` |
| Auth | `/api/v1/auth` |
| Continuity | `/api/v1/continuity` |
| Continuity plans | `/api/v1/continuity-plans` |
| Continuity rules | `/api/v1/continuity-rules` |
| Dependencies | `/api/v1/dependencies` |
| Issues | `/api/v1/issues` |
| Queue | `/api/v1/queue` |
| Rate | `/api/v1/rate` |
| Reading-order groups | `/api/v1/reading-order-groups` |
| Releases | `/api/v1/releases` |
| Roll | `/api/v1/roll` |
| Sessions | `/api/v1/sessions` |
| Snooze | `/api/v1/snooze` |
| Threads | `/api/v1/threads` |
| Undo | `/api/v1/undo` |

## Intentional legacy aliases (`/api`)

Two categories of bare `/api/<segment>` routes are retained deliberately and must remain
on the explicit allowlist:

1. **Compatibility aliases** — the families above that also keep a legacy
   `/api/<family>` path (`auth`, `queue`, `rate`, `roll`, `sessions`, `snooze`,
   `threads`, `undo`). These are tested backwards-compatibility surfaces; maintained
   first-party consumers should prefer the `/api/v1` equivalent.
2. **Tooling-only surfaces** — administrative and non-production routes that are never
   versioned client resources: `admin`, `bug-reports`, and `debug` (the latter mounted
   only outside production).

Any other bare `/api` route is a regression and fails the contract test.

## Collections

Collections were removed. The OpenAPI document contains no supported Collections route,
schema, or operation. References to a *retired* `collection_id` query parameter in legacy
operation descriptions are documentation of removed behavior, not supported surface.

## Verification

Run the contract test (no database required):

```bash
pytest tests/test_api_v1_canonical_contract.py
```

It asserts: no duplicate `operationId`s, no supported Collections surface, every canonical
family above has an `/api/v1` route, and every bare `/api` alias is on the allowlist.
Regenerate the schema with `python scripts/generate_openapi_types.py` after any routing
change.
