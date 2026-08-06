# Production E2E data safety

Production browser monitoring uses a dedicated account and must never create records under a personal account.

## Naming contract

Every production-created thread must set `is_test=true` and use this title format:

```text
[E2E] <run-id> <description>
```

The run ID may contain letters, numbers, dots, underscores, and hyphens. Tests should derive it from the GitHub run ID and attempt so records remain attributable without including comic or account data.

Each test that mutates production must delete its own records in a `finally` block or fixture teardown. The janitor is a recovery boundary for interrupted processes, not the normal cleanup path.

## Scheduled janitor

`scripts/cleanup_production_e2e_data.py` runs before scheduled production performance monitoring. It deletes a thread only when all of these are true:

- the thread belongs to the exact user identified by `PROD_E2E_ACCOUNT_EMAIL`;
- `Thread.is_test` is true;
- the title strictly matches the production E2E naming contract;
- the thread is older than 24 hours.

The command is idempotent and supports `--dry-run`. Its output contains only the cutoff, candidate count, account-found state, and dry-run state. It never logs titles, record IDs, email addresses, tokens, or database connection details.

Required repository secrets:

- `PROD_E2E_ACCOUNT_EMAIL`
- `PROD_E2E_DATABASE_URL`
- `PROD_E2E_STORAGE_STATE_JSON`

Credential rotation must update all three boundaries together and verify a manual workflow run before scheduled monitoring resumes.
