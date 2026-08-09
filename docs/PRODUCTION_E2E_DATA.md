# Production E2E data safety

Production browser monitoring creates a disposable account through the real registration UI for every run. It must never use a personal account.

## Disposable account contract

The workflow generates a unique username, email, and password from the GitHub run ID and attempt. The password is masked immediately, exists only in the runner environment, and is never stored as a repository secret or artifact.

The only database credential is the existing GitHub Actions repository secret:

- `NEON_DIRECT_DATABASE_URL`

The scheduled workflow registers through `/register` and writes the resulting Playwright storage state only to the GitHub runner temporary directory. Authentication cookies and tokens are therefore short-lived runner files. They are never uploaded as artifacts.

Usernames and emails follow strict reserved patterns containing the GitHub run ID and attempt. The janitor uses `NEON_DIRECT_DATABASE_URL` and refuses to delete accounts outside those patterns or accounts containing application data.

## Naming contract

Every production-created thread must set `is_test=true` and use this title format:

```text
[E2E] <run-id> <description>
```

The run ID may contain letters, numbers, dots, underscores, and hyphens. Tests should derive it from the GitHub run ID and attempt so records remain attributable without including comic or account data.

Each test that mutates production must delete its own records in a `finally` block or fixture teardown. The janitor is a recovery boundary for interrupted processes, not the normal cleanup path.

## Account cleanup

`scripts/cleanup_production_e2e_accounts.py` runs both before and after production monitoring. Exact post-run cleanup deletes the current disposable account. Pre-run cleanup reaps accounts older than 24 hours after interrupted runs.

- both username and email match the reserved run-scoped patterns;
- the run ID and attempt encoded in the username and email agree;
- stale cleanup considers only accounts older than 24 hours;
- the account owns no threads, reading orders, dependency groups, or continuity rules.

The command is idempotent and supports `--dry-run`. Its output contains only counts, the cutoff, and dry-run state. It never logs usernames, email addresses, IDs, tokens, passwords, or database connection details.

## Recovery

If registration or cleanup fails, do not substitute a personal account and do not weaken the ownership guard. Inspect the workflow artifacts and repair the registration or cleanup boundary. A later run may reap an interrupted account only after it crosses the 24-hour cutoff.
