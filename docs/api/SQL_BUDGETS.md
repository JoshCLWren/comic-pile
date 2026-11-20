# Historical SQL-budget registry (retired November 15, 2026)

The owner canceled the mandatory per-route SQL-budget and
`pg_stat_statements` parity program. The existing
`docs/api/sql-budget-sources.json` entries are historical route metadata used
by the currently generated inventory. **They are not active performance
requirements, test coverage targets, or grounds for new issues.**

Do not add budgets for newly migrated routes or require a numeric query ceiling
in CI or review. The standing engineering standard is in `AGENTS.md`:
prefer set-based, bounded PostgreSQL queries; avoid N+1 and repeated round
trips; preserve correct transactions and ownership; and investigate measured
performance regressions with targeted checks when they actually occur.

<<<<<<< HEAD
`pg_stat_database` transaction and block deltas, HTTP response bytes, wall
time, and child CPU are reported separately. Those database-wide deltas can
include unrelated connections and are contextual telemetry, not exact route
counts. Measured cases also read the isolated role's nested
(`toplevel = false`) statement counter, so trigger and function work caused by
the mutated rows is recorded separately from the declared
application/transaction-control budget and must not grow between the small and
large fixtures.

The source registry currently marks 26 operations `pending-fixture`; those are
explicit proof gaps under #4737, not passing measurement evidence.
=======
The original tracking issues #4737 and #4988 and their children #5146–#5151
were closed as not planned. Their dedicated unfinished PRs were closed unmerged.
>>>>>>> origin/main
