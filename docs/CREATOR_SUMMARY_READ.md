# Requested creator summary reads

`GET /api/v1/creators/summaries` uses
`load_creator_summary_inputs_for_creators` in
`app/repositories/creator_summary.py`. The full-library reader remains available
for creator discovery and detail callers that need all owned issues.

The requested summary reader runs three user-scoped statements:

1. Read stored manual credits once per thread. Existing normalized-name hashing
   supplies stable manual IDs; no new provider identities are invented.
2. Count global rated, read-unrated and upcoming coverage in PostgreSQL. Coverage
   recognizes usable confirmed credits even when their creator was not requested.
3. Return only requested provider credits and applicable manual-credit issues,
   with their latest effective rating. A usable confirmed credit suppresses
   manual fallback independently of the requested IDs. Malformed credit arrays
   are guarded before JSONB expansion.

The global coverage statement returns one row. Unrelated owned issues and their
ratings are not transferred to Python. Manual credits remain one read per
thread, rather than being repeated on each issue. Requested attribution rows
still scale with the number of matching issues and credits, not just the number
of requested people.

`tests/test_creator_read_performance_regression.py::test_summary_projection_bounds_transferred_rows`
compares the full and requested projections for 100/1,000 issues and 1/2/5/20
requested keys. It checks exact credit parity, returned issue/rating sets,
constant query count and global coverage, and prints measured durations and
Python profile call counts for both readers. The fixture analyzes local tables
because autovacuum cannot analyze uncommitted fixture rows. For one requested
creator the 1,000-issue fixture returns 50 matching issues instead of loading all
1,000 issues and their ratings. Local profiled timings are diagnostic, not a
production latency guarantee; reduced transferred rows alone do not establish
an end-to-end latency improvement.
