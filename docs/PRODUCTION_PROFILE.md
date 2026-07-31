# Production profiling

ComicPile has two production browser profiles with deliberately different jobs.

- `test:e2e:prod-profile` is the faithful real-user profile. It uses the existing `Josh_Digital_Comics` production account, preserves the source HAR's action breadth and rhythm, and confines destructive mutations to disposable fixture threads inside that account.
- `test:e2e:prod-profile:small-account` is the earlier disposable-user smoke profile from PR #675. It is useful for a fast health check, but it is not equivalent to the original human session and must not be used for performance comparisons against that HAR.

The source HAR itself is credential-bearing and remains local. The repository contains only a generated, sanitized workload manifest.

## Source workload manifest

Generate the checked-in manifest from the original local HAR:

```bash
python scripts/build_production_profile_manifest.py \
  --har '/mnt/data/comic-pile.vercel.app_Archive [26-07-30 15-30-27].har' \
  --output frontend/src/test/fixtures/production-profile-workload.json
```

The builder validates the 198-request API stream and known route anchors before writing anything. It records:

- all 28 chronological action groups;
- route templates, methods, query shapes, and body shapes;
- source concurrency groups and pauses;
- expected follow-up requests and request-count ranges;
- route-level p50, p90, p95, p99, and maximum latency;
- duplicate GET bursts;
- mutation categories and cold/warm classification fields;
- the source account-complexity baseline;
- a coverage disposition for every original user action.

It never writes captured cookies, authorization headers, response bodies, raw request values, usernames, titles, tokens, cursors, or numeric resource IDs.

## Authentication

The real-user profile requires an existing authenticated production session. Authentication sources are tried in this order:

1. `PROD_PROFILE_STORAGE_STATE`, pointing to a local Playwright storage-state file.
2. `PROD_PROFILE_HAR_PATH`, pointing to the local credential-bearing source HAR.

Neither file may be committed. The test removes any browser access token before the first navigation so the measured startup exercises `/api/auth/me` 401, `/api/auth/refresh`, and the authenticated retry. Recording starts before navigation, and there is no health-check warmup.

Example using the HAR as the local cookie source:

```bash
PROD_BASE_URL=https://comic-pile.vercel.app \
PROD_PROFILE_HAR_PATH='/mnt/data/comic-pile.vercel.app_Archive [26-07-30 15-30-27].har' \
  pnpm --filter frontend run test:e2e:prod-profile
```

Example using an authenticated storage state:

```bash
PROD_BASE_URL=https://comic-pile.vercel.app \
PROD_PROFILE_STORAGE_STATE="$HOME/.local/share/comic-pile/prod-storage-state.json" \
  pnpm --filter frontend run test:e2e:prod-profile
```

The expected username defaults to `Josh_Digital_Comics` and can be overridden with `PROD_PROFILE_EXPECTED_USERNAME` only when intentionally targeting another account.

## Real-user workload

The workload uses the surrounding production account for realistic collection, thread-list, stale-thread, current-session, history, analytics, authentication, cache-key, and invalidation complexity. It dynamically records the account's current size instead of asserting that the July 30 baseline will remain frozen forever.

The measured actions include:

1. Cold refresh-token application startup with concurrent account reads.
2. Home, history, and analytics navigation.
3. Repeated ratings, rolls, reading-order reads, connected-thread reads, snooze, pending dismissal, pending selection, and dice changes.
4. Queue movement, progressive searches, a 40-issue thread load, batched issue-dependency loading, mark-read, mark-unread, add, reorder, delete, and metadata edit operations.
5. Dependency candidate reads, blocked-dependency reads, dependency creation, verification, and deletion.
6. Completed-thread reactivation and final account refreshes.
7. Cleanup and verification that no unrelated thread state changed.

The bug-report action is represented in the manifest and its exact request shape is constructed during the test, but it is not sent because production has no supported cleanup path for generated reports.

## Safe fixture boundary

Every destructive operation is restricted to timestamped threads prefixed with `PROD PROFILE FIXTURE`:

- one 40-issue primary thread with mixed read and unread state;
- one dependency target;
- one completed thread for reactivation coverage.

Before fixture creation, the profile fingerprints every unrelated thread's title, format, status, issue counts, notes, and queue position. The test deletes fixture dependencies and threads in `finally`, then compares the unrelated-thread fingerprint and fails unless cleanup is verified.

Fixture setup and cleanup requests are recorded separately from workload requests. They are not included in the action-for-action performance comparison.

## Rating reliability

Every rating records the exact `/api/rate/` request, request-body shape, browser timing, HTTP status or transport failure, request ID, cache status, database-query count, `Server-Timing`, Vercel request identifier, and all follow-up reads.

The browser timeout remains 10 seconds. The five-second profiling budget is unchanged.

When a rating request times out, the profile queries authoritative thread state and classifies the outcome as:

- `definite-success` when the response succeeds or authoritative state confirms the rating committed;
- `definite-failure` when the server returns a definite non-success response;
- `unknown-outcome` when neither result can be proven.

A client timeout alone is never reported as a failed write.

## Timing and cold-start evidence

The default pause scale is `1`, preserving the human session's pauses. For selector or harness development only, use `PROD_PROFILE_PAUSE_SCALE=0`. A scaled run is reported as a divergence and should not be used for final performance comparison.

The test does not infer a cold start from wall-clock latency. Set `PROD_PROFILE_INVOCATION_CLASSIFICATION` only when the runner has Vercel evidence, and optionally provide a short `PROD_PROFILE_INVOCATION_EVIDENCE` description. Otherwise the report says `unconfirmed`.

Useful overrides:

```bash
PROD_PROFILE_MAX_API_MS=5000
PROD_PROFILE_DUPLICATE_WINDOW_MS=250
PROD_PROFILE_PAUSE_SCALE=1
```

Raising the latency budget is not an accepted fix for a regression.

## Outputs

Every run attaches:

- `production-profile.json`;
- `production-profile.sanitized.har.json`;
- `production-profile.action-timeline.json`;
- `production-profile.route-summary.json`;
- `production-profile.source-comparison.json`;
- `production-profile.bug-report-construction.json`;
- a Playwright trace and screenshot on failure.

The main report includes the workload-manifest version, source fingerprint, current account-complexity snapshot, action and route timing, request count, p50/p90/p95/p99/maximum latency, cold/warm evidence, HTTP and transport failures, ambiguous mutation outcomes, duplicate GET bursts, legacy and batched dependency counts, cache outcomes, database-query totals, request IDs, `Server-Timing`, Vercel identifiers, cleanup verification, and workload divergence.

Generated artifacts contain no cookies, authorization headers, access tokens, refresh tokens, CSRF values, response bodies, or raw mutation values.

## Comparison protocol

Only compare runs that use this same real-user manifest and an unscaled pause sequence. Keep cold and warm distributions separate.

A defensible comparison set contains:

- at least five immediate warm repetitions;
- at least three Vercel-confirmed cold repetitions;
- one access-token-refresh repetition;
- one rating-focused repetition after an idle interval.

Report per-action and per-route changes, equivalent request-count changes, cache effects, median and tail latency, failure rate, and mutation-ambiguity rate. The small-account smoke profile is not a control for this workload.

## Small-account smoke profile

The earlier profile remains available under its explicit name:

```bash
PROD_BASE_URL=https://comic-pile.vercel.app \
  pnpm --filter frontend run test:e2e:prod-profile:small-account
```

It registers a disposable user, creates three threads, and performs a small happy-path journey. It intentionally does not model the existing account's history, cache surface, thread count, authentication refresh, repeated mutations, searches, dependency management, reactivation, or full source-HAR request sequence.
