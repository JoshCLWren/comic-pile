# Changelog

## 2026-08-06

**Faster and more resilient startup**

- Preview deployments now fail closed if they inherit the Production database, Redis credentials, or restricted routes, protecting live data and cache quota during branch testing ([#876](https://github.com/JoshCLWren/comic-pile/pull/876)).
- Scheduled production browser checks now safely remove only stale, ownership-scoped E2E records, preventing test data buildup without touching real reading data ([#864](https://github.com/JoshCLWren/comic-pile/pull/864)).
- The production frontend is now served as static Vercel output, keeping the home page and React routes out of the FastAPI cold-start path ([#863](https://github.com/JoshCLWren/comic-pile/pull/863)).
- A branded bootstrap shell keeps useful loading and reconnecting feedback visible until the application is actually ready ([#859](https://github.com/JoshCLWren/comic-pile/pull/859)).
- Returning to an iOS tab after suspension now revalidates the session, refreshes cached data, and offers retry or reload recovery instead of leaving an empty app ([#854](https://github.com/JoshCLWren/comic-pile/pull/854)).
- Production probes now track document, application shell, first API response, and Queue readiness over time, with bounded history and regression reporting ([#861](https://github.com/JoshCLWren/comic-pile/pull/861)).
- Separate liveness, dependency-health, and warm-up endpoints make operational checks cheaper and more precise ([#860](https://github.com/JoshCLWren/comic-pile/pull/860)).

**Crossovers and reading order**

- Reading-order groups are now presented as Crossovers throughout the Roll experience ([#856](https://github.com/JoshCLWren/comic-pile/pull/856)).
- A dedicated Crossovers page supports creating, inspecting, renaming, and deleting crossover groups from the app ([#857](https://github.com/JoshCLWren/comic-pile/pull/857)).
- Crossover management can add an inclusive range of issues from a thread in one operation, with duplicate-safe results and validation ([#858](https://github.com/JoshCLWren/comic-pile/pull/858)).
- Fixed Roll crossover loading to use the real versioned API routes ([#822](https://github.com/JoshCLWren/comic-pile/pull/822)).

**Authentication, feedback, and Queue**

- Authentication routes and maintained frontend callers now use canonical `/api/v1/auth/*` paths while retaining compatibility aliases ([#825](https://github.com/JoshCLWren/comic-pile/pull/825), [#826](https://github.com/JoshCLWren/comic-pile/pull/826), [#827](https://github.com/JoshCLWren/comic-pile/pull/827)).
- Feedback can now be submitted explicitly as either a bug report or a feature request, with matching GitHub labels ([#855](https://github.com/JoshCLWren/comic-pile/pull/855)).
- Queue reposition previews now display the full selected move distance instead of always showing one position ([#821](https://github.com/JoshCLWren/comic-pile/pull/821)).
- Frontend API contracts now derive additional auth types from generated OpenAPI output, and shared query keys establish targeted cache-update behavior ([#820](https://github.com/JoshCLWren/comic-pile/pull/820), [#823](https://github.com/JoshCLWren/comic-pile/pull/823), [#824](https://github.com/JoshCLWren/comic-pile/pull/824)).

**Factory visibility and reliability**

- GitHub labels now expose factory ownership and lifecycle state on issues and pull requests ([#819](https://github.com/JoshCLWren/comic-pile/pull/819)).
- Factory worktrees refresh from current main before each heartbeat, the free-model pool includes curated Google and OpenRouter options, and transient failures rotate models without prematurely retiring them ([#814](https://github.com/JoshCLWren/comic-pile/pull/814), [#818](https://github.com/JoshCLWren/comic-pile/pull/818)).

## 2026-08-05

**Roll mutation recovery**

- Rating and snooze operations now reconcile server-committed changes after browser timeouts or failed refreshes, and stale bootstrap responses can no longer overwrite newer reconciled state ([#784](https://github.com/JoshCLWren/comic-pile/pull/784), [#798](https://github.com/JoshCLWren/comic-pile/pull/798), [#799](https://github.com/JoshCLWren/comic-pile/pull/799), [#800](https://github.com/JoshCLWren/comic-pile/pull/800)).
- Deterministic latest-session lookups gained an index and phase-level observability for current-session and History reads ([#778](https://github.com/JoshCLWren/comic-pile/pull/778), [#801](https://github.com/JoshCLWren/comic-pile/pull/801)).

**Reading-order foundations**

- Added the ownership-scoped named dependency-group API, typed frontend client, and Roll presentation used by the later Crossovers interface ([#790](https://github.com/JoshCLWren/comic-pile/pull/790), [#805](https://github.com/JoshCLWren/comic-pile/pull/805), [#807](https://github.com/JoshCLWren/comic-pile/pull/807), [#808](https://github.com/JoshCLWren/comic-pile/pull/808), [#809](https://github.com/JoshCLWren/comic-pile/pull/809)).

**Maintenance and safeguards**

- Completed removal of retired Reviews persistence and kept completed Queue threads collapsed by default ([#810](https://github.com/JoshCLWren/comic-pile/pull/810), [#811](https://github.com/JoshCLWren/comic-pile/pull/811)).
- CI now rejects stale or untracked generated OpenAPI artifacts ([#812](https://github.com/JoshCLWren/comic-pile/pull/812), [#813](https://github.com/JoshCLWren/comic-pile/pull/813)).
- The factory now prioritizes backlog delivery, respects review gates, and may merge only after the complete exact-head gate set is satisfied ([#797](https://github.com/JoshCLWren/comic-pile/pull/797)).

## 2026-08-04

**Mobile overlays and data restore**

- Modals and the Queue position menu now share a document-level overlay lifecycle and stable stacking contract, preventing nested overlays from being clipped or layered incorrectly ([#786](https://github.com/JoshCLWren/comic-pile/pull/786), [#787](https://github.com/JoshCLWren/comic-pile/pull/787), [#789](https://github.com/JoshCLWren/comic-pile/pull/789)).
- Local restore now remaps retained export relationships safely instead of reusing production graph identifiers ([#785](https://github.com/JoshCLWren/comic-pile/pull/785)).
- OpenCode provider rotation now exhausts available providers correctly instead of getting stuck on one failing provider ([#792](https://github.com/JoshCLWren/comic-pile/pull/792)).


## 2026-08-03

**OpenCode model discovery, rotation, and attribution (factory tooling)**

- Added `scripts/opencode-model-manifest.sh`: a shared, flock-protected model manifest helper (`init`, `set`, `record`, `confirmed`, `next`, `pending`, `summary`) that tracks probe status, tool-call support, last probe time, and per-model usage.
- Added `scripts/opencode-model-scout.sh`: a concurrent ACP tool-call prober that probes candidate models through `opencode run` in parallel, kills any probe that stops writing to its heartbeat file (default 15 minutes), and updates the manifest eagerly as each probe finishes.
- The factory runner (`comic-pile-opencode-factory.sh`) now rotates across confirmed models instead of always using the paid DeepSeek subscription: an explicit `--model` or `OPENCODE_MODEL` wins, otherwise it round-robins least-used confirmed models via `next`, falling back to `COMIC_PILE_DEFAULT_MODEL`.
- The runner writes a per-heartbeat heartbeat file and a watchdog kills a hung run that has produced no output for `FACTORY_HEARTBEAT_TIMEOUT` (default 60s).
- The overnight supervisor (`comic-pile-opencode-factory-overnight.sh`) now launches the model scout in `--watch` mode alongside the factory, tracks it with its own pid file, and reports confirmed models in `status`.
- Added `.githooks/prepare-commit-msg`: every commit is attributed with a `Model: <id>` trailer from `OPENCODE_MODEL` (skipped for merges, amends, and squash commits). Factory PR bodies are attributed with the producing model.
- `scripts/install-git-hooks.sh` installs the new hook, preserving any original user hooks in `.sample` backups on first run; `factory-policy.yml` syntax-checks the new shell scripts.

**Production migrations on Vercel/Neon**

- Production schema migrations now run automatically in the GitHub Actions `deploy-production.yml` workflow, before `vercel deploy`, against the Neon main-branch database.
- The workflow fetches the main branch's direct (unpooled) connection URL at runtime via the Neon API using the `NEON_API_KEY` secret and `NEON_PROJECT_ID` variable created by the Neon GitHub integration, then runs `alembic upgrade head`. The old `NEON_DIRECT_DATABASE_URL` secret is no longer required.
- The workflow fails closed if the Neon credentials are missing or if multiple Alembic heads exist, and verifies the applied revision with `alembic current`.
- The dead Railway migration path is gone: `make deploy-prod` now dispatches the `deploy-production.yml` workflow, and `make prod-migrate` runs `alembic upgrade head` against Neon via the Neon API (or an explicit `NEON_DIRECT_DATABASE_URL` override).
- `PROD_BASE_URL` now defaults to `https://comic-pile.vercel.app`.

**Remove reviews from the backend (#627)**

- Removed the retired Reviews API: the empty reviews router is unwired from `app/main.py`, the thread-scoped `GET /threads/{id}/reviews` endpoint is gone, and `app/api/review.py`, `app/schemas/review.py`, and `app/models/review.py` are deleted.
- Removed the `Review` model exports and the user/thread/issue `reviews` relationships, the `get_owned_review_or_404` ownership helper, and the admin `POST /admin/import/reviews/` endpoint.
- Removed the review-only `review_url` and `last_review_at` thread columns from the model, schemas, serializers, and snapshot restore paths.
- Clone/export scripts no longer export or import reviews or the retired thread columns.
- The `reviews` table and the orphaned thread columns remain in the database for one release pending production verification (follow-up issue #741); no destructive migration ships yet.

**Collections feature removed (#636)**

- The Collections feature is retired: the roll-pool collection dropdown, collection dialog, collection badges, collection query keys and context, and all collection API routes are gone.
- Roll and Queue operate on the full user thread library without collection filtering or collection-dependent branches.
- The `collections` table and `threads.collection_id` column are dropped by migration; the prod-clone export/import and user-merge scripts no longer handle collections.

## 2026-08-01

**TanStack Query collections pilot (#701)**

- Introduced `@tanstack/react-query` as the standard server-state layer via a small pilot migration of the collections read + create mutation.
- Collections now load through a single deduplicated TanStack query (`useCollectionsQuery`) shared across consumers, instead of per-provider manual `useState`/`useEffect` fetches.
- Create mutation invalidates only the `['collections']` query key; all 401 responses and 403 responses whose detail is "Not authenticated" are never retried (the axios interceptor already handles token refresh); other 403 errors and transient failures retry up to 3 times.
- Added the migration recipe to `docs/REACT_ARCHITECTURE.md` so future features can follow the same pattern.
- Queue, Roll, and other pages keep their existing custom-hook data fetching.

**Production request observability (#678)**

- Production now defaults to WARNING root log level instead of ERROR, so structured `Slow HTTP request` and `Client Error` warnings reach deployment logs (previously suppressed).
- Documented that `Server-Timing` is emitted locally but absent from responses observed through the current Vercel deployment; the precise removal layer remains unisolated, so timing evidence should currently be read from `X-Request-ID`, `X-App-DB-Queries`, `X-App-Cache`, runtime logs, and the structured slow-request warnings.
- Added regression coverage for log-level resolution and slow-request warning emission.

## 2026-07-24

**Incremental session history (#608)**

- History page now loads quickly with an initial page of sessions.
- Users can load additional sessions on demand by clicking "Load More Sessions".
- Loading states, errors, and retry options are displayed clearly during load-more operations.

## 2026-07-19

**Queue card swipe action containment**
- Queue cards now fill their grid row so hidden swipe actions remain fully contained when a neighboring blocked card is taller.
