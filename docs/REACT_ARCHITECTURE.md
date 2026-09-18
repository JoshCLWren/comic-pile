# React & TanStack Query Architecture for Comic Pile

## Overview

This document describes the modern TypeScript/React frontend architecture for Comic Pile, a dice-driven comic reading tracker. The frontend uses React 19 with Vite for development and bundling, Tailwind CSS for styling, TanStack Query (`@tanstack/react-query`) for canonical server state management, and OpenAPI-generated types for strict backend contract parity.

Hand-rolled `useState`/`useEffect` fetching and manual session context caching are obsolete. All server data flows through TanStack Query keys and centralized cache effects.

---

## Technology Stack

- **Build Tool**: Vite 7.x — Fast ESM development server and Rollup production bundler.
- **Framework**: React 19.x — Modern UI library with Concurrent features, Transitions, and Suspense.
- **Language**: TypeScript (strict mode) — Strong static typing across all components, hooks, and services.
- **Server State Management**: `@tanstack/react-query` v5 — Declarative data fetching, caching, automatic deduplication, garbage collection, and query invalidation.
- **HTTP Client**: Axios — Configured instance in `services/api.ts` with interceptors for authentication, base URL configuration, and error normalization.
- **Routing & Navigation**: React Router DOM 7.x — Client-side declarative routing with code splitting and route prefetching (`useRoutePrefetch`).
- **Styling & Visual Contract**: Tailwind CSS 4.x — Governed strictly by [`FRONTEND_VISUAL_GRAMMAR.md`](FRONTEND_VISUAL_GRAMMAR.md).
- **3D Graphics**: Three.js — Visual dice roller with lazy-loaded geometries and physics integration.

---

## Project Structure

The frontend structure under `frontend/src/`:

```
frontend/src/
├── components/          # Reusable UI components (Navigation, Modals, Virtualized lists)
├── contexts/            # Focused client state providers (Toast, NavCollapse, BugReportRestore, PositionMenu)
├── hooks/               # Domain hooks powered by TanStack Query & custom interactions
├── pages/               # Route-level page components (RollPage, QueuePage, etc.)
├── query/               # Canonical TanStack Query configuration & cache effects
│   ├── queryClient.ts   # Global QueryClient singleton & default stale/gc policies
│   ├── queryKeys.ts     # Type-safe, canonical hierarchical query keys
│   ├── cacheEffects.ts  # Centralized mutation cache updates and invalidation helpers
│   └── routePrefetch.ts # Canonical query prefetching for route transitions
├── routes/              # Route module definitions and lazy loading boundaries
├── services/            # API services and OpenAPI integrations
│   ├── api.ts           # Configured Axios client with auth token interceptors
│   ├── theme.ts         # Multi-surface theme runtime & preference persistence
│   └── ...              # Domain-specific API service endpoints
├── types/               # TypeScript interfaces & OpenAPI-generated contract models
├── utils/               # Pure utility functions (dates, parsing, topological sort)
├── App.tsx              # App provider tree, routing table, and layout shells
├── main.tsx             # Root React 19 hydration entry point
└── index.css            # Tailwind CSS root imports and theme variables
```

---

## Server State Management (TanStack Query)

### 1. Canonical Query Keys (`frontend/src/query/queryKeys.ts`)

All query keys are defined hierarchically to prevent cache collision and enable targeted invalidations:

```typescript
export const queryKeys = {
  queue: {
    all: ['queue'] as const,
    pages: () => ['queue', 'pages'] as const,
    list: ({ search, sort, pageSize }) => [...],
  },
  session: {
    all: ['session'] as const,
    current: () => ['session', 'current'] as const,
    detail: (sessionId: number) => ['session', 'detail', sessionId] as const,
  },
  roll: {
    all: ['roll'] as const,
    bootstrap: () => ['roll', 'bootstrap'] as const,
  },
  thread: {
    all: ['thread'] as const,
    summary: (threadId: number) => ['thread', 'summary', threadId] as const,
    detail: (threadId: number) => ['thread', 'detail', threadId] as const,
    issuePages: (threadId: number) => ['thread', threadId, 'issues'] as const,
  },
  // ... dependencies, readingPlans, comicVine, analytics, creator, etc.
} as const
```

### 2. Centralized Cache Effects (`frontend/src/query/cacheEffects.ts`)

Whenever a mutation occurs (rating a comic, reordering the queue, updating thread metadata), cache updates and invalidations must use the centralized functions in `cacheEffects.ts`:

- `applyRatedThreadCache(client, thread)`: Updates active thread in-place and invalidates current session.
- `applyUpdatedThreadCache(client, thread)`: Updates detail/summary cache and invalidates queue pages, session, and roll bootstrap.
- `invalidateAfterQueueMutation(client)`: Resets paginated queue loader and refetches session and roll bootstrap.
- `applyEditedThreadToQueuePages(client, thread)`: Updates thread metadata across all loaded infinite query pages in-place without triggering network refetches.
- `optimisticallyUpdateThreadCache(client, threadId, update)`: Safe optimistic updates with rollback closures.

**Rule:** Never write hand-rolled `useState`/`useEffect` fetch lifecycles with manual `isMounted` flags for server state. Use `useQuery`, `useInfiniteQuery`, or `useMutation` hooks.

---

## Routing & Layout Architecture

### Route Splitting & Prefetching

Routes are lazy-loaded via `routes/routeModules.ts` using `lazyRoute()`. When an authenticated user is detected, `useRoutePrefetch(enabled)` warms the bundle chunks in the background for instant navigation.

### Layout Shells

1. **`AuthenticatedLayout`**: Grid layout (`md:grid-cols-[auto_minmax(0,1fr)]`) containing the unified `Navigation` sidebar/bottom bar and main responsive container.
2. **`PublicLayout`**: Minimal container for public auth routes (`/login`, `/register`).
3. **`ResumeRecovery` & `AuthResumeBoundary`**: Handles silent session token renewal and graceful recovery after return visits.

### Scroll Ownership

Route scroll restoration has one owner: `useScrollRestoration` in
`frontend/src/hooks/useScrollRestoration.ts`, coordinated through
`frontend/src/scroll/scrollCoordinator.ts`. That module is the only production
code allowed to call `window.scrollTo` to restore a prior route position.

- **Route/resume restoration** (`restoreRouteScrollPosition`) covers POP/PUSH
  navigation, reloads, bfcache restores, and visibility resume. It waits for
  layout to settle through `waitForLayoutSettled`, with bounded stable animation
  frames rather than a fixed timeout. A user scroll gesture ends the settle
  watch so restoration does not fight intentional scrolling.
- **Feature scrolling** is limited to intentional in-page transitions, such as
  Roll moving between dice and rating regions or Help jumping to a glossary
  anchor. These use `requestSemanticScroll` or `scrollToTopSemantic`, which
  defer while route restoration is settling.
- **Virtualizers** own measurement and rendering, not navigation restoration.
  Queue edge auto-scroll remains an explicit user-gesture scroll.
- **ResumeRecovery** owns data and auth recovery, not viewport position. It
  refreshes the scoped resume set through `invalidateAfterResumeRecovery` in
  `frontend/src/query/cacheEffects.ts` and never changes the viewport.

Do not add another route-restoration `window.scrollTo` path, a separate scroll
retry timer, or an unscoped `invalidateQueries()` call in a resume path. The
guard test `frontend/src/unit/scrollOwnership.test.ts` protects the single
navigation-scroll owner.

---

## Client State vs Server State

- **Server State**: Managed strictly through TanStack Query (`queryClient`, `queryKeys`, `cacheEffects`).
- **Global UI State**: Managed via dedicated context providers:
  - `ToastProvider`: Floating notifications and action confirmations.
  - `NavCollapseProvider`: Desktop navigation sidebar expanded/collapsed state.
  - `BugReportRestoreProvider`: Preserves bug report drafts across view changes.
  - `PositionMenuProvider`: Keeps position-menu interaction state available to its consumers.
- **Authentication**: `AuthProvider` lives in `frontend/src/App.tsx`. It owns
  authentication identity; server session, queue, and roll data stay in
  TanStack Query rather than a manual `SessionContext` cache.
- **Visual Design Rules**: All component styling must conform to [`docs/FRONTEND_VISUAL_GRAMMAR.md`](FRONTEND_VISUAL_GRAMMAR.md).
