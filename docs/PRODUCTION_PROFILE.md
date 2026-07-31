# Production profile

The production profile turns a real browser journey into a repeatable request-budget smoke test. It was derived from a Chrome HAR captured while using ComicPile normally after the Vercel, Neon, and Upstash migration.

Unlike replaying the HAR literally, the profile never depends on captured thread, issue, session, dependency, or user IDs. Every run creates a disposable authenticated user and discovers the runtime resources through the UI and API.

## Run it

```bash
PROD_BASE_URL=https://comic-pile.vercel.app \
  pnpm --filter frontend run test:e2e:prod-profile
```

The profile deliberately runs only in Chromium and with one worker because it measures one production user journey rather than browser compatibility.

## Journey

The test performs these actions against the supplied deployment:

1. Verify `/health`.
2. Register and authenticate a disposable user.
3. Create a 40-issue thread plus two smaller roll-pool threads.
4. Load the roll page, roll, and submit a rating.
5. Open the queue and navigate to the dynamically created thread.
6. Open the thread edit dialog, show all issues, and toggle the first issue's read state.
7. Visit history and analytics.
8. Attach a normalized JSON request report to the Playwright result.

The normalization replaces numeric path IDs and dynamic query cursors. That lets the test enforce route-level behavior without baking production data into the script.

## Default budgets

| Check | Default |
| --- | ---: |
| Maximum API requests | 60 |
| Maximum API duration | 5,000 ms |
| Duplicate GET burst window | 250 ms |
| Legacy per-issue dependency requests | 0 |
| Thread dependency batch requests | exactly 1 |
| Failed API responses or transport failures | 0 |

Override the numeric budgets when intentionally characterizing a slower environment:

```bash
PROD_BASE_URL=https://comic-pile.vercel.app \
PROD_PROFILE_MAX_API_MS=8000 \
PROD_PROFILE_MAX_API_REQUESTS=75 \
PROD_PROFILE_DUPLICATE_WINDOW_MS=150 \
  pnpm --filter frontend run test:e2e:prod-profile
```

Budget overrides must be positive numbers. Invalid values fail immediately instead of silently falling back to defaults. Raising a threshold should be treated as an explicit profiling choice, not a way to make a regression disappear.

The overall Playwright journey allows up to five minutes for cold starts and sequential navigation. That does not relax the five-second budget applied to each profiled API request.

## Report

Each run attaches `production-profile.json`, containing:

- every normalized API request and status;
- wall-clock duration;
- request IDs plus `Server-Timing`, `X-App-Cache`, and `X-App-DB-Queries` when the deployment exposes them;
- median, p95, and maximum API latency;
- cache-status counts;
- duplicate GET bursts;
- failed and slow requests.

The generated user and threads remain in the target deployment, matching the repository's existing production smoke-test behavior. Their timestamped names make them easy to identify and periodically clean up.
