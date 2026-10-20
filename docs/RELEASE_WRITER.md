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

Before retrying a source, the release writer checks `/api/v1/releases/source` with repository, PR number, and merge SHA. Existing matching records are left alone. A 409 source-identity conflict is treated as an error and is never silently overwritten.

The release-writer agent gathers merged-PR context through `scripts/release_writer.py` read-only subcommands (`pr`, `files`, `issues`) rather than raw `gh api` calls, so the GitHub read surface stays inside the credential-holding helper and the agent stays structurally read-only.

Public changes are validated by `scripts/release_writer.py` before being sent to the release API. Strictly internal changes are emitted as an explicit machine-readable `internal`/`skipped` classification in the workflow log instead of forcing a public What's New entry.

## Public classification grounding

`issues` returns full linked-issue context (number, title, state, labels, bounded body, detected `scope_fences`, and parent/dependency `references`) so classification is grounded in issue prose rather than issue numbers.

A public publication must carry `provenance_json` classification evidence: `classification`, `classification_reason`, `user_visible_evidence`, `reader_reachable`, `inspected_issue_numbers`, `scope_fences`, and `contradicting_evidence`. The helper and the release API both reject a public payload that:

- omits classification evidence, or sets `reader_reachable` to anything but `true`;
- records a non-empty `scope_fences` list without `contradicting_evidence` naming the shipped reader path;
- promises a reader capability in reader-facing copy without `reader_reachable_path`;
- claims a reader capability in copy while the merged diff changes no reader-facing product surface and a scope fence or undocumented reader path contradicts it.

Grounding only blocks on positive evidence, so an unavailable GitHub read never blocks an otherwise valid publication. Internal skips record `reader_reachable: false` with an empty `user_visible_evidence` and accept `inspected_issue_numbers` and `scope_fences` for audit.

## Deterministic internal classification

`scripts/release_writer.py` classifies a release as `internal` when the reader-facing copy carries engineering artifacts, so a dev-internal note never reaches the public feed:

- **Decisive artifacts** always classify the record as internal. They are engineering artifacts that reader-facing copy cannot contain: diff fragments (`diff --git`, `+++ b/`), endpoint literals (`POST /api/v1/threads`, `/api/roll`), factory automation wording (`factory session`, `factory review`), `style-drift`, `fixed-model`, `OmniRoute`, and phrases such as `internal refactor` or `implementation detail`.
- **Suggestive terms** are ordinary words that are also engineering jargon (`factory`, `controller`, `evidence`, `inspection`, `proof`, `reliability`, `audit`, `endpoint`, `literal`, `jargon`). They classify the record as internal only when the payload records no reader-facing evidence. Recorded reader-facing evidence therefore keeps a note public.

Ordinary product words never classify a note on their own. Reading sessions, proofs, audits, reliability, endpoints, and inspections are ordinary language for a reader of a comic tracker, so a note such as "Restore your reading session" stays public.

The copy fields (title, summary, body) are scanned field-by-field, joined with newlines so a diff frame at the start of the summary or body is still a line-start match.

Scope fences are a separate statement scan of the pull-request and linked-issue text: only phrases that say the reader-visible portion is not in the change (`no frontend callers`, `internal refactor: behavior preserved`, `out of scope`) block an uncontradicted public note. The decisive artifact table above is deliberately not applied to descriptions, so quoting an artifact such as `POST /api/roll` or a diff frame in a pull-request or issue body never blocks a reader-facing note whose served copy is clean. Worker attribution boilerplate (`Produced by fixed-model Factory 46 (...)`, `Worker: opencode-free-model-factory-46`) is removed before the fence scan, because it describes how the change was produced rather than what the change is. A real internal statement, such as `internal refactor: behavior preserved`, still fences normally.
