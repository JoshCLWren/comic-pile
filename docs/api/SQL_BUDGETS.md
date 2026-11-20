# Native SQL budgets

`docs/api/sql-budget-sources.json` is the editable source for `sql_budget` on
native v2 operations. The route generator overlays these entries onto
`docs/api/v2-route-inventory.json`; the latter is bot-owned and must not be
edited in a PR. A budget records the maximum combined application and
transaction-control statements and whether that maximum grows with input data.
The `basis` text explains the reviewed handler call path.
`runtime_overhead_statements` records measured pool checkout probes separately
from handler statements; `max_statements` includes that overhead.

`tests/test_v2_sql_budget_inventory.py` checks source-to-generated parity,
budget arithmetic, explicit DB-free exemptions, and the inventory gap set.
The HTTP parity cases in `native/roll-service/parity/test_http_*_n1.py` exercise
small and large fixtures or a single successful request. They use
`pg_stat_statements` with `track=all`, filtered to the isolated
`roll_test_dml` role and current database. A missing statement view fails the
measured tests; it is not treated as a passing budget. The dedicated
`test_sql_budget_measurement.py` checks that an extra service-role query is
visible to the counter.

`pg_stat_database` transaction and block deltas, HTTP response bytes, wall
time, and child CPU are reported separately. Those database-wide deltas can
include unrelated connections and are contextual telemetry, not exact route
counts. Measured cases also read the isolated role's nested
(`toplevel = false`) statement counter, so trigger and function work caused by
the mutated rows is recorded separately from the declared
application/transaction-control budget and must not grow between the small and
large fixtures.

The source registry currently marks 26 operations `pending-fixture`; those are
explicit proof gaps under #4988, not passing measurement evidence.
