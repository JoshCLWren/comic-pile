# Roll v2 parity diagnostic

Run a read-only comparison on seeded PostgreSQL data:

```bash
uv run python -m scripts.check_roll_v2_parity --user-id USER_ID --session-id SESSION_ID --die-size 100
```

Use the generated reader/session IDs from the fixture. The command runs the production
projection and independent reference reads in one repeatable-read transaction, rolls back,
and exits nonzero for named discrepancies. It prints projection and reference timings.
It checks returned frontier identities/numbers, thread facts, group routes, canonical
progress/effective ratings, and session last-read. It does not prove full bootstrap pool
membership, cover rendering, random stale selection, or browser migration completion.

For reproducible small, normal, and large fixture evidence:

```bash
uv run pytest tests/test_roll_v2_parity_harness.py -q -s --no-cov
```

The tests compare real projections at pool sizes 0, 1, 20, and 100; assert the production
projection's 1–3 query budget; print timings; and deliberately corrupt frontier/rating/
last-read results to prove the comparator detects differences. They also preserve the
current Issue number and null-rating-event rules. These comparisons are independent of
the production projection query helpers; performance timings are diagnostic, not a flaky
wall-clock pass/fail threshold.
