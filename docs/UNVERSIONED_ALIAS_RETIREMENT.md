# Unversioned alias retirement

Owner objective: reduce the Rust cutover surface by retiring unused aliases,
after checking actual callers. API versions identify contracts, not languages.

This slice removes 16 Python route-methods without a new Rust implementation.
The same method and suffix under `/api/v1` remain unchanged:

| Retired method | Unversioned path |
| --- | --- |
| POST | `/api/threads/` |
| GET | `/api/threads/stale` |
| POST | `/api/threads/reactivate` |
| PUT, DELETE | `/api/threads/{thread_id}` |
| POST | `/api/threads/{thread_id}/set-pending` |
| PUT | `/api/threads/{thread_id}/test-backdate` |
| POST | `/api/threads/{thread_id}:migrateToIssues` |
| POST | `/api/threads/{thread_id}:migrateToIssuesSimple` |
| POST | `/api/threads/{thread_id}:setCurrentIssue` |
| GET | `/api/sessions/` |
| GET | `/api/sessions/current/` |
| GET | `/api/sessions/{session_id}/details` |
| POST | `/api/sessions/{session_id}/restore-session-start` |
| GET | `/api/undo/{session_id}/snapshots` |
| POST | `/api/undo/{session_id}/undo/{snapshot_id}` |

## Caller evidence

`frontend/src/services/api.ts` uses `/api` as its base. The retained thread,
reading-session and undo services explicitly request `/v1/...`; thread listing
uses `/v2/threads`. They need no product transport changes.

The remaining executable bare-thread callers were the create/migrate methods in
`scripts/comic_pile_api.py` (since deleted) and browser setup <!-- docs-path-check: ignore --> in `helpers.ts`, `fixtures.ts`,
`cbl-replace-review.spec.ts`, and `issue-1885-roll-target-sizes.spec.ts`. Those
callers now use the existing `/api/v1/threads/...` equivalents. Two session
semantic tests now exercise `/api/v1/sessions/current/`. Observability fixtures
and retirement probes can still mention retired paths without calling them as
supported product operations.

## Remaining owner-objective scope

The auth count is still 24 native route-methods: eight each under `/api/auth`,
`/api/v1/auth` and `/api/v2/auth`. Product auth services and the CLI use v2.
Removing native auth compatibility aliases also requires updating the published
same-path contract and baseline native ingress generation; this slice does not
claim that work complete.

Three native compatibility aliases also remain: `GET /api/threads/{thread_id}`,
`GET /api/sessions/{session_id}`, and
`GET /api/sessions/{session_id}/snapshots`. This slice retires the 16 listed
Python operations, not every bare path in those families.

The two Python Roll aliases are retained: `POST /api/roll/override` and
`GET /api/roll/events/{event_id}/recommendation-explanation`. Their migration
has a live owner in PR #5244; coordinate its alias retirement rather than
rewriting that work concurrently.

## Rollout and verification

Only source route fragments are committed. The route-regeneration workflow owns
`vercel.json`, the inventory, generated rewrite fragments and the AGENTS table.
The local three-step generation pipeline verifies the removal before commit;
the bot must regenerate after merge before production ingress acceptance.

Require focused route/caller tests, whole-repo Python lint/type checks,
frontend lint/type/build and transport tests, exact-head CI and independent
review. Deployment acceptance must confirm retired aliases return 404 and
retained authenticated thread/session/undo flows work. Local checks do not
establish production acceptance.
