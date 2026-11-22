# Historical SQL-budget registry (retired November 15, 2026)

<<<<<<< HEAD
`docs/api/sql-budget-sources.json` is the editable source for `sql_budget` on
native v2 operations. The route generator overlays these entries onto
`docs/api/v2-route-inventory.json`; the latter is bot-owned and must not be
edited in a PR. A budget records the maximum combined application and
transaction-control statements and whether that maximum grows with input data.
The `basis` text explains the reviewed handler call path.
`runtime_overhead_statements` records measured pool checkout probes separately
from handler statements; `max_statements` includes that overhead. When a route
executes statements inside a trigger or function, `max_nested_statements` bounds
those nested executions separately and they do not inflate the top-level
`total_statements` or `max_statements` values. A measured route must match its
declared budget exactly, so `max_statements` carries no slack: one deliberately
added extra query has to exceed the declared maximum instead of still fitting
inside it.
=======
The owner canceled the mandatory per-route SQL-budget and
`pg_stat_statements` parity program. The existing
`docs/api/sql-budget-sources.json` entries are historical route metadata used
by the currently generated inventory. **They are not active performance
requirements, test coverage targets, or grounds for new issues.**
>>>>>>> origin/main

Do not add budgets for newly migrated routes or require a numeric query ceiling
in CI or review. The standing engineering standard is in `AGENTS.md`:
prefer set-based, bounded PostgreSQL queries; avoid N+1 and repeated round
trips; preserve correct transactions and ownership; and investigate measured
performance regressions with targeted checks when they actually occur.

The original tracking issues #4737 and #4988 and their children #5146–#5151
were closed as not planned. Their dedicated unfinished PRs were closed unmerged.
