# Production E2E data safety

Production browser monitoring uses a dedicated account and must never create records under a personal account.

## Dedicated account contract

Create one normal ComicPile production user used only by automated browser monitoring. The account does not need administrative privileges and must not contain personal reading data.

Store its credentials in GitHub Actions repository secrets:

- `PROD_E2E_ACCOUNT_USERNAME`
- `PROD_E2E_ACCOUNT_PASSWORD`
- `PROD_E2E_ACCOUNT_EMAIL`
- `PROD_E2E_DATABASE_URL`

The scheduled production workflow signs in through the real `/login` UI and writes the resulting Playwright storage state only to the GitHub runner temporary directory. Authentication cookies and tokens are therefore short-lived runner files rather than a long-lived storage-state secret. They are never uploaded as artifacts.

`PROD_E2E_ACCOUNT_EMAIL` identifies the same dedicated account to the production-data janitor. `PROD_E2E_DATABASE_URL` is used only for that ownership-scoped cleanup path.

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

The command is idempotent and supports `--dry-run`. Its output contains only the cutoff, candidate count, account-found state, and dry-run state. It never logs titles, record IDs, email addresses, tokens, passwords, or database connection details.

## Rotation and recovery

Rotate the account password by updating `PROD_E2E_ACCOUNT_PASSWORD`; no checked-in storage-state file needs replacement. If the account username or email changes, update the corresponding repository secrets together. After any credential change, run the Production Performance workflow manually and verify authentication, cleanup, and the production milestones before relying on the next scheduled run.

If authentication begins failing, do not substitute a personal account. Repair or recreate the dedicated account, update the repository secrets, and rerun the workflow. Test-created data remains recognizable by the `[E2E]` prefix and `is_test=true` boundary.
