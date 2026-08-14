# Release writer operations

ComicPile publishes release-ledger records after pull requests merge. Implementation branches do not need to publish database records themselves.

## Credentials

Configure `RELEASE_WRITER_TOKEN` in both places with the same strong random value:

- GitHub repository Actions secrets, for `.github/workflows/release-writer.yml`.
- The production Vercel environment, where the release API validates `X-Release-Writer-Token`.

Also keep the existing `NVIDIA_API_KEY` Actions secret configured for OpenCode model access. Never commit either value. The OpenCode release-writer agent is not permitted to inspect credentials directly; it can only invoke `scripts/release_writer.py`, which reads the release token from its environment when making the authenticated API call.

## Triggering

The workflow runs after a pull request is actually merged to `main`. Closing an unmerged pull request does not run release publication. It can also be dispatched manually for one merged PR and runs hourly reconciliation for recent merged PRs that do not yet have ledger records.

Release publication is deliberately asynchronous. A release-writer failure records a failed workflow run but does not change, revert, or block the already-merged product pull request.

## Reconciliation and provenance

Recent reconciliation starts with `python scripts/release_writer.py recent <repository> <limit>`. The helper reads closed pull requests from GitHub, filters to merges into `main`, sorts the complete merged set by exact `merged_at` timestamp, and emits only the requested newest rows. This keeps shell quoting, API pagination, and model output truncation out of recent-PR discovery.

Before retrying a source, the release writer checks `/api/v1/releases/source` with repository, PR number, and merge SHA. Existing matching records are left alone. A 409 source-identity conflict is treated as an error and is never silently overwritten.

Public changes are validated by `scripts/release_writer.py` before being sent to the release API. Strictly internal changes are stored as durable `visibility=internal` release records. Public release reads filter those rows out, while source reconciliation can still see them so hourly runs do not repeatedly reclassify the same internal pull request.
