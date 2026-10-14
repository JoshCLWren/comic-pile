# Reader Ownership Consistency

Canonical boundary contract for graph and library write edges (issue #3225).

Reader ownership is an **enforced property** of every graph and library write
boundary, not an application convention. Catalog identity
(`catalog_issues`, shared between readers since #3220) is a *shared reference*,
never authorization evidence: two readers may legitimately reference the same
catalog row, and that reference grants neither reader access to anything else
belonging to the other.

## What is enforced where

| Edge | Enforcement | Rejects raw SQL | Rationale |
|---|---|---|---|
| `threads.next_unread_issue_id` -> `issues.id` | PostgreSQL trigger `trg_threads_frontier_ownership` + `app/services/ownership_consistency.ensure_thread_frontier_issue` | yes | The frontier must belong to **that exact thread**, not merely to a thread the reader owns. |
| `sessions.pending_thread_id` -> `threads.id` | PostgreSQL trigger `trg_sessions_pending_ownership` + `app/services/ownership_consistency.ensure_pending_thread_owned` | yes | A reading session may only pin a thread owned by its own reader. |
| Reading Plan issue membership (`reading_plan_issues`) | `app/services/reading_plan_normalization.ensure_plan_issue_membership_owned` | no | The edge crosses two tables, so no foreign key can express it; `rebuild_plan_membership` is the single funnel every membership write path uses. |
| Reading Plan dependency membership (`reading_plan_dependencies`) | `link_dependency_to_plan` (existing) | no | Both endpoints are validated against the plan owner's library before the link is written. |
| Dependency endpoints (`dependencies`) | `app/services/dependency_service.create_dependency` (existing) | no | Both endpoints are resolved to threads owned by the requesting reader before the edge is created. |
| Tag assignments (`tag_assignments`) | `app/services/tag_service` (existing) | no | Polymorphic `target_type`/`target_id` with no foreign key by design; a private tag may only be attached to a target the tag owner owns. |

Everything above is a *write boundary*: each is checked before any row is
persisted, and each reports a missing reference exactly like another reader's
reference so it cannot be used as an existence oracle.

## Why triggers instead of composite foreign keys

A composite foreign key for the frontier would be
`(next_unread_issue_id, id) -> issues(id, thread_id)`. On PostgreSQL 16 the only
delete action that preserves the current `ON DELETE SET NULL` behaviour is
`ON DELETE SET NULL (next_unread_issue_id)`, because plain `ON DELETE SET NULL`
would also null the not-null primary key `threads.id`. It would additionally make
every existing `Thread`/`Issue` relationship join ambiguous for SQLAlchemy.

For `sessions`, `pending_thread_id` is nullable and is cleared as the roll
advances, so a composite foreign key adds nothing over the existing
single-column one while costing the same delete-semantics problem.

The triggers therefore enforce *only* the new invariant. The existing
single-column foreign keys - and every delete path that relies on their
`ON DELETE SET NULL` behaviour - are untouched.

## What is deliberately not constrained

`sessions.pending_issue_id` is **not** constrained to `pending_thread_id`. Roll
advances `pending_thread_id` on every selection while `pending_issue_id` keeps
the reader's last explicitly pinned issue, so a stale cross-thread pin is
normal reader state, not a violation. The pin is only ever written from an issue
the caller already owns.

## Introducing the constraints safely

Constraints are introduced only after read-only violation detection:

- `scripts/audit_reader_ownership_violations.py` is the repeatable read-only
  report. It returns, per violation class, a count plus a bounded list of
  primary keys - never titles, notes, ratings, corrections, tags, events, or any
  other reader content - so it is safe to attach to a change or a deploy log.
  It exits `1` while any violation exists.
- `alembic/preflight/m5d400000001.json` runs the same detection as a
  machine-enforced, read-only production preflight immediately before
  `alembic upgrade head`, so a deploy fails with production unchanged rather
  than installing the triggers over invalid rows.

Nothing in this slice deletes, remaps, or auto-repairs an existing row. Ambiguous
ownership stays a human decision.

## Shared catalog access grants nothing else

A reader who can see a shared `CatalogIssue` still cannot reach another reader's
personal notes, corrections, tags, events, or read state. Those live on rows
whose ownership resolves through `threads.user_id`, and every read and write
boundary above resolves ownership the same way. Regression coverage lives in
`tests/test_reader_ownership_consistency.py`.

## Related

- [`docs/READING_GRAPH_ADR.md`](READING_GRAPH_ADR.md) - Threads own natural
  frontiers; canonical issue Dependencies encode hard prerequisites; Reading
  Plans own reader intent.
- [`docs/READING_SESSION_NAMING.md`](READING_SESSION_NAMING.md) - `ReadingSession`
  is durable reading history, never an auth session.
- [`docs/issue-plans/3225.md`](issue-plans/3225.md) - the delivered plan and
  acceptance evidence for this slice.