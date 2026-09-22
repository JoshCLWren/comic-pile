# React Architecture for Comic Pile

This document describes the **live** React frontend for Comic Pile. It is the
frontend architecture reference linked from the docs hub. `AGENTS.md` remains
the terse, authoritative rule set for agents working in this repository; when
this document and `AGENTS.md` disagree, `AGENTS.md` wins.

Comic Pile's frontend is a React 19 single-page application built with Vite,
styled with Tailwind CSS 4, and typed with TypeScript. **Server state is managed
exclusively with TanStack Query** (`@tanstack/react-query`). The pre-Query
custom `useState`/`useEffect` fetch hooks and the old
`SessionContext`/`CacheContext` providers were removed during the React Query
migration (#1719 / #1758 / #1759) and #2573, and must not be reintroduced.

## Technology Stack

- **Build Tool**: Vite 8.x — fast dev server with HMR, production build to
  `../static/react/`, SRI-injected assets (`vite-plugin-sri`), and manual chunk
  splitting (`three` and `vendor`) in `frontend/vite.config.ts`.
- **Framework**: React 19.x — function components with hooks, lazy route loading.
- **Routing**: React Router DOM 7.x — client-side routing under `BrowserRouter`.
- **HTTP Client**: Axios — the shared instance in `frontend/src/services/api.ts`
  owns base URL `/api`, CSRF headers for state-changing methods, access-token
  refresh with single retry, login redirect, and response unwrapping.
- **Server State**: TanStack Query 5.x (`@tanstack/react-query`) — the only
  server-state cache. Reads use `useQuery`, writes use `useMutation`, and every
  cache write/invalidation lives in `frontend/src/query/cacheEffects.ts`.
- **List Virtualization**: `@tanstack/react-virtual` — Queue and similar large
  lists measure/renders through virtualizers.
- **Styling**: Tailwind CSS 4.x via `@tailwindcss/postcss`. The canonical visual
  contract is [`FRONTEND_VISUAL_GRAMMAR.md`](FRONTEND_VISUAL_GRAMMAR.md).
- **Type Safety**: TypeScript strict mode. Frontend transport types are
  generated from the backend OpenAPI schema (see
  [`FRONTEND_OPENAPI_TYPES.md`](FRONTEND_OPENAPI_TYPES.md)).
- **3D Graphics**: Three.js for the dice, lazily loaded through
  `LazyDice3D` / `Dice3D`.

## Project Structure

The frontend source is a TypeScript layout under `frontend/src/`:

```text
frontend/
├── src/
│   ├── main.tsx              # React entry point: root, ToastProvider, AppErrorBoundary
│   ├── App.tsx               # AuthProvider, QueryClientProvider, routes, layouts
│   ├── components/           # Reusable UI components (Modal, OverlayPortal, Navigation, ...)
│   ├── pages/                # Route-level page modules (RollPage/, QueuePage/, ...)
│   ├── routes/               # routeModules.ts — single source of split chunk loaders
│   ├── hooks/                # Custom hooks, including TanStack Query wrappers
│   ├── query/                # queryClient.ts, queryKeys.ts, cacheEffects.ts, routePrefetch.ts
│   ├── services/             # api.ts (Axios instance) + per-domain api-*.ts modules
│   ├── contexts/             # Client-side providers (Toast, NavCollapse, PositionMenu, ...)
│   ├── scroll/               # scrollCoordinator.ts — sole scroll-restoration owner
│   ├── pagination/           # useInfiniteCollection, collectAllPages, PaginationSentinel
│   ├── generated/            # openapi.ts + openapi.json generated from the backend schema
│   ├── types.ts              # frontend domain/view-model types and barrel
│   ├── types/                # more specific type modules (rollBootstrap.ts, ...)
│   ├── config/               # runtime feature flags (features.ts)
│   ├── utils/                # shared helpers (apiError, dateFormat, runtimeChecks, ...)
│   ├── devtools/             # dice playground and debug surfaces
│   ├── assets/               # static assets imported by components
│   ├── @types/               # ambient type shims (three) for untyped deps
│   ├── unit/                 # Vitest unit tests (colocated under src/unit)
│   └── test/                 # TypeScript Playwright E2E specs
├── public/                   # Static assets served as-is
├── index.html                # HTML template
├── vite.config.ts            # Vite configuration (proxy, build output, chunks)
├── tsconfig.json             # Strict TypeScript configuration
└── package.json              # Dependencies and scripts (pnpm)
```

Notable point: the old `.jsx` source layout (top-level `Header.jsx`,
`Footer.jsx`, `App.jsx`, `main.jsx`) no longer exists. Pages are organized as
module directories (`pages/RollPage/`, `pages/QueuePage/`) so each screen can
own its coordinator hooks, domain helpers, and sub-components.

## Server State: TanStack Query

Server state is **never** managed with hand-rolled `useState`/`useEffect` fetch
hooks. The pre-Query pattern (custom hooks with `isMounted` refs and imperative
`setData` calls) was removed; do not reintroduce it. The canonical patterns:

- `frontend/src/query/queryClient.ts` — the single shared `QueryClient`
  instance with app defaults (`staleTime` 30s, `gcTime` 5min,
  `refetchOnWindowFocus: false`, no TanStack retry for 401/auth-403 and other
  deterministic 4xx, up to 3 retries for transient/network/5xx, mutations
  `retry: false`).
- `frontend/src/query/queryKeys.ts` — **all** query-key builders live here as a
  hierarchical per-domain namespace (`queue`, `session`, `roll`, `thread`,
  `dependencies`, `analytics`, ...) with `all` / `list` / `detail` / `page`
  shapes and `as const`. Pagination cursors live in `pageParam`, never in the
  key, and filter params are normalized so identical filter sets hash to one
  stable key. Never inline raw key arrays inside components or hooks.
- `frontend/src/query/cacheEffects.ts` — the **canonical cache-effect
  location**. All cache writes, invalidations, and optimistic updates go through
  helpers here (`optimisticallyUpdateThreadCache`, `applyEditedThreadToQueuePages`,
  `invalidateAfterQueueMutation`, `invalidateAfterResumeRecovery`, ...). Direct
  `setQueryData` / `invalidateQueries` / `removeQueries` calls in production
  code are prohibited outside this module (except the documented roll-bootstrap
  reconciliation seam in `useRollBootstrap.ts`).

Hook conventions (mirroring the `AGENTS.md` frontend section):

- **Reads (`useQuery`)**: wrap a service call from `services/api.ts`, gate with
  `enabled`, key from `queryKeys.*` via a `frontend/src/hooks/use*.ts` wrapper,
  and return `{ data, isPending, isError, refetch }`.
- **Writes (`useMutation`)**: `mutationFn` calls the API service; `onSuccess`
  performs a cache effect (usually an invalidation/update helper from
  `cacheEffects.ts`). The mutation is the single source of truth for the write;
  do not call `refetch()` after an invalidation helper that already triggers
  refetch.
- **Optimistic updates**: call the matching `cacheEffects.ts` helper in
  `onMutate`, keep the returned rollback function, and invoke it in `onError` so
  the prior cache is restored. Optimistic writes always pair with a rollback
  path.

The repo-level guard test `frontend/src/unit/single-cache-architecture.test.ts`
fails if `CacheContext`, `CacheProvider`, `useCache`, `SessionContext`, or
`SessionProvider` are reintroduced under `frontend/src/`.

### Bounded Thread Queries

Thread list data is loaded through bounded, screen-specific query hooks. The
universal `useThreads()` hook was removed because it hydrated every page of the
thread list (page_size 200 plus automatic page traversal) regardless of the
screen, which defeated the per-screen cache boundaries.

**Supported bounded entry points**:

- `useQueueThreads(...)` in `frontend/src/hooks/useQueue.ts` — the Queue
  screen's bounded infinite-list query (`QUEUE_PAGE_SIZE = 50`). Fetches the
  first page on mount, supports an optional `search`, and only advances with an
  explicit pagination cursor. Pages are threaded through
  `queryKeys.queue.pages()` / `queryKeys.queue.list()` (cursor in
  `pageParam`, not the key).
- `useThread(id)` in `frontend/src/hooks/useThread.ts` — a single thread's
  details (thread detail screen).
- `useStaleThreads(days)` in `frontend/src/hooks/useThread.ts` — stale-thread
  summary data for the Roll screen.

**Rule**: Do not reintroduce a universal thread-list hook that hydrates the
entire library across all screens. The guard test
`frontend/src/unit/boundedThreadQuery.guard.test.tsx` fails if a universal
`useThreads` export is reintroduced or if the queue query auto-traverses pages.

## Routing, Code Splitting, and Route Prefetch

- `frontend/src/routes/routeModules.ts` is the single source of truth for the
  code-split entry chunks. `App.tsx` builds every `React.lazy()` route from
  these loaders (`lazyRoute('roll')`, `lazyRoute('queue')`, ...). Collections
  were removed in #636; no collection loader exists (or may be added).
- Routes render inside a `Suspense` boundary with a loading fallback.
  `RouteChunkPrefetcher`/`useRoutePrefetch` warm the likely-next chunk via
  `frontend/src/query/routePrefetch.ts` (idle-scheduled, deduplicated, bounded —
  at most one fetch per likely-next chunk plus one Queue first-page data warm-up,
  publicly cancellable, errors swallowed).

Current URL patterns (React Router preserves these):

| URL | Page | Notes |
|-----|------|-------|
| `/` | RollPage | Default home page with dice roll |
| `/queue` | QueuePage | Thread list, reordering, completion |
| `/thread/:id` | ThreadDetailView | Single-thread detail and issues |
| `/creators/:creatorKey` | CreatorDetailPage | Creator summaries and analytics |
| `/history` | HistoryPage | Event log with undo |
| `/sessions/:id` | SessionPage | Session details and snapshots |
| `/crossovers`, `/crossovers/:group` | CrossoversPage / CrossoverDetailPage | Crossover groups |
| `/continuity-plans*` | ContinuityPlannerPage / ContinuityPlansIndexPage | Reading-plan builder |
| `/whats-new` | WhatsNewPage | Release feed |
| `/glossary` | HelpPage | Glossary/help |
| `/identity-inbox` | IdentityInboxPage | Comic-identity corrections |
| `/login`, `/register` | LoginPage / RegisterPage | Public auth pages |
| `/rate`, `/analytics`, `/help` | — | Redirect aliases to current destinations |

## Scroll Ownership

Route scroll restoration has exactly one owner (#2582): the route restoration
layer (`useScrollRestoration` in `frontend/src/hooks/useScrollRestoration.ts`),
coordinated through the shared module
`frontend/src/scroll/scrollCoordinator.ts`. That module is the only production
code allowed to call `window.scrollTo` to restore a prior route position.

- **Route/resume restoration** covers POP/PUSH navigation, reloads, bfcache
  restores, and visibility resume. Correctness settles against an explicit
  layout-readiness contract (`waitForLayoutSettled`: stable animation frames,
  bounded) — never a fixed timeout. A user-driven gesture ends the settle watch.
- **Feature semantic scrolling** is the narrow exception: Roll may move between
  the dice and rating regions and Help may jump to a glossary anchor, but only
  through `requestSemanticScroll` / `scrollToTopSemantic`, which defer while a
  route restore is settling.
- **Virtualizers own measurement/rendering, not navigation**; their drag
  edge auto-scroll is an explicit user-gesture scroll, not a restore.
- **ResumeRecovery owns data/auth recovery, not viewport position**; it
  refreshes the scoped resume set through `invalidateAfterResumeRecovery` in
  `frontend/src/query/cacheEffects.ts`.

**Rule**: Do not add another `window.scrollTo` restoration path, another scroll
retry timer, or an unscoped `invalidateQueries()` in a resume path. The guard
test `frontend/src/unit/scrollOwnership.test.ts` fails if a second
navigation-scroll owner is introduced.

## Overlays and UI Primitives

Dialogs and menus follow the overlay ownership rules documented in
`frontend/AGENTS.md`:

- `Modal` — full-dialog primitives with focus trap, Escape handling, backdrop
  ownership, focus lock, and stacking counter.
- `OverlayPortal` with `layer="menu"` — position menus, popovers, and selectors.
- `OverlayPortal` with `layer="dialog"` — portaled dialogs that delegate
  focus/Escape/stacking to `Modal`.

Ad-hoc `fixed inset-0` / `role="dialog"` / `aria-modal` overlays outside these
approved primitives are not allowed. Interaction policy (no hidden gesture-only
actions) is documented in [`REACT_INTERACTION_POLICY.md`](REACT_INTERACTION_POLICY.md).

## Auth and Client-side State

- **Auth** lives in `AuthProvider` (in `frontend/src/App.tsx`): bootstraps the
  session against `/v1/auth/me`, renews it with the refresh cookie, synchronizes
  logout across tabs via a `BroadcastChannel`, and gates routes with
  `ProtectedRoute` / `PublicRoute`.
- **Client-side (non-server) state** stays in dedicated providers:
  `ToastProvider`, `NavCollapseProvider`, `BugReportRestoreProvider`,
  `PositionMenuProvider`. Dice selection and similar UI state is local.
- **Session data is server state**: the authoritative current session comes from
  React Query via `useSession` / `queryKeys.session.*` and the roll bootstrap.
  The old `SessionContext` global session mirror and the Map-based
  `CacheContext` were deleted in #2573 — there is exactly one server-state cache
  (TanStack Query) and one session source (the roll bootstrap).

## API Service Layer

- `frontend/src/services/api.ts` exports the shared Axios instance: base URL
  `/api`, `X-CSRF-Token` headers on state-changing methods, 401 → token refresh
  → single retry, login redirect, and typed request helpers that unwrap
  `response.data`.
- Per-domain service modules (`api-queue.ts`, `api-threads.ts`, `api-rate.ts`,
  `api-continuity-plans.ts`, `api-issues.ts`, ...) own the endpoint calls and
  response shapes for each screen family.
- Transport types are generated from the backend OpenAPI schema into
  `frontend/src/generated/openapi.ts`; domain/view-model types live in
  `frontend/src/types.ts`. The exact boundary rules are in
  [`FRONTEND_OPENAPI_TYPES.md`](FRONTEND_OPENAPI_TYPES.md).

## Data Flow

1. A screen mounts and a `useQuery`/`useInfiniteQuery` wrapper (from
   `frontend/src/hooks/`) reads through a `queryKeys.*` key.
2. The query calls a service function in `frontend/src/services/`, which hits a
   FastAPI endpoint under `/api/v1/*` (or a tested legacy alias).
3. Responses are cached in the shared `QueryClient`; components re-render from
   the single cache.
4. User actions call `useMutation`; `onSuccess` runs a `cacheEffects.ts` helper
   that writes or invalidates the exact affected keys, and the cache refetch
   updates every subscribed consumer.

## Build Pipeline

### Development Mode

```bash
pnpm run dev       # or: make dev (starts backend on :8000 and frontend :5173)
```

Vite serves `http://localhost:5173` with HMR and proxies `/api` to the FastAPI
backend (`http://localhost:8000`, override with `VITE_API_URL`).

### Production Build

```bash
pnpm run build     # in frontend/
```

Vite builds to `../static/react/` with SRI hashes and module splitting
(`index-*.js`, `assets/index-*.css`, separate `three` and `vendor` chunks).

### FastAPI Integration

FastAPI serves the built SPA whenever `serve_frontend` is enabled (`app/main.py`):

- The React app is served at the root `/` from `static/react/index.html` (with
  no-store headers); `/react` and `/react/` redirect to `/`.
- Hashed build assets under `static/react/assets` are mounted at `/assets` with
  immutable cache headers (public, one-year max-age) via
  `CacheControlledStaticFiles`.
- `/static` mounts the static directory, and production startup asserts the
  frontend assets exist before serving.

**Access React App**: `http://localhost:8000/` — API at `http://localhost:8000/api/*`
uses the same backend. Vercel serves the same static build + FastAPI function for
production (see [`ARCHITECTURE.md`](ARCHITECTURE.md) and
[`VERCEL_ARCHITECTURE.md`](VERCEL_ARCHITECTURE.md)).

## Styling Approach

The canonical visual contract is [`FRONTEND_VISUAL_GRAMMAR.md`](FRONTEND_VISUAL_GRAMMAR.md) —
semantic `data-theme` roles (`--theme-*` tokens) in `frontend/src/styles.css`,
standard spacing scale, mobile-first responsive pairs, and the three live themes
(`classic`, `ink-gold`, `command-center`). Theme persistence matches
[`frontend/src/services/theme.ts`](../frontend/src/services/theme.ts)
(`restoreStoredTheme` in `main.tsx` renders the locally persisted theme before
network/auth work). New visual values must follow the grammar's incremental
migration policy rather than inventing a local dialect.

## 3D Dice Component

`components/Dice3D.tsx` renders an interactive Three.js die inside a
`position: relative` container. It is wrapped by `components/LazyDice3D.tsx`,
which suspends Three.js loading until first render; the Roll screen uses
`LazyDice3D` to avoid blocking initial load.

**Prop interface** (`components/diceTypes.ts`): `sides`, `value`,
`isRolling`, `freeze`, `lockMotion`, `color`, `onRollComplete`, `renderConfig`
(see `components/diceRenderConfig.ts`).

**Lifecycle**: the Three.js scene and renderer are created once on mount and
disposed on unmount. Geometry and texture rebuild on `sides` / `color` /
`renderConfig` changes; the animation loop restarts on `freeze` /
`lockMotion` / `isRolling` changes so the loop always sees current ref values.

## Testing Strategy

- **Unit tests**: Vitest suites colocated under `frontend/src/unit/` (React
  Testing Library + `msw` for API mocking), plus guard tests that enforce
  architectural invariants (single cache, scroll ownership, bounded thread
  queries). Run with `cd frontend && pnpm test`.
- **Style audit**: `pnpm run test:style-audit` / `audit:style` guard the visual
  grammar; `docs/FRONTEND_VISUAL_GRAMMAR.md` is the canonical contract.
- **E2E tests**: TypeScript Playwright specs under `frontend/src/test/`. They
  run against the production build in `static/react/`, so **build first**
  (`pnpm run build` and then `pnpm run test:e2e`, or `make verify-e2e`).
  Chromium is the maintained required Playwright target.
- **Type contract tests**: compile-time Vitest tests keep the alias-bound
  `frontend/src/types.ts` exports identical to the generated OpenAPI schemas.
- **Backend tests**: existing pytest suites cover the API endpoints that the
  frontend consumes (see [`API.md`](API.md)).

## Key Decisions & Rationale

### Why TanStack Query instead of custom fetch hooks?
One cache, one key schema (`queryKeys`), one cache-effect module
(`cacheEffects`), automatic dedup/refetch, and server/client state separation.
Hand-rolled `useState`/`useEffect` fetch scaffolding was removed with the
migration; keeping two caching layers caused competing-cache bugs.

### Why Vite over Create React App?
Faster builds (esbuild), better HMR, modern config, direct `outDir` control for
`static/react/`, and SRI support.

### Why Axios over the Fetch API?
Interceptors for auth refresh, CSRF, retries, and login redirect; automatic
JSON parsing; timeout support; typed request helpers.

### Why Tailwind CSS 4.x over 3.x?
The new PostCSS plugin (`@tailwindcss/postcss`), faster builds, and simpler
configuration, governed by the semantic roles in the visual grammar.

## References

- [AGENTS.md](../AGENTS.md) — Project guidelines and conventions for coding agents
- [FRONTEND_VISUAL_GRAMMAR.md](FRONTEND_VISUAL_GRAMMAR.md) — canonical visual contract
- [FRONTEND_OPENAPI_TYPES.md](FRONTEND_OPENAPI_TYPES.md) — OpenAPI type boundary
- [REACT_INTERACTION_POLICY.md](REACT_INTERACTION_POLICY.md) — interaction/gesture rules
- [API.md](API.md) — REST API contracts and examples
- [Architecture overview](ARCHITECTURE.md) — repository-level architecture