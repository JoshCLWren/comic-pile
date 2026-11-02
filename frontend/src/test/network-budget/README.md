# Network-budget harness

Deterministic route-wide HTTP request budgets for public and auxiliary views.
Owned by task #4504 under parent #4499. Feature-route budgets are owned by
peer worker #4503; this namespace only owns public/auth/auxiliary flow and the
shared harness contract.

## What it measures

Every request is recorded at the **axios adapter boundary** after request
interceptors (auth headers, retry, refresh) and before the response interceptor
unwraps the payload. The app's real axios singleton, interceptors, providers,
`AppRoutes`, route guards, and React Query options stay in place; only the
terminal network adapter is replaced.

A recorded row is `METHOD /api/path?sorted-query xCOUNT`:

```text
GET /api/v1/auth/me x1
GET /api/v1/identity-inbox?limit=1&offset=0 x1
GET /api/v1/releases/?limit=20&offset=0 x1
```

Query keys and values are sorted, so parameter order never changes a budget.

## Files

| File | Purpose |
| --- | --- |
| `requestLedger.ts` | Adapter recorder, canonical rows, duplicate/unhandled detection |
| `appNetworkHarness.tsx` | Mounts real `AppRoutes` + providers with stub transport |
| `appNetworkProbes.tsx` | Auth-status, router-location, and navigate bridges |
| `routeInventory.ts` | Single audited route table + `App.tsx` parser |
| `routeBudgets.ts` | Exact cold-mount budgets per public/auxiliary route |
| `publicRoutes.network.test.tsx` | Public routes, redirects, 404, demo |
| `auxiliaryRoutes.network.test.tsx` | Authenticated shell, glossary, what's-new |
| `authTransitions.network.test.tsx` | Login/logout, cross-account cache isolation |
| `routeInventory.test.ts` | Fails when `App.tsx` and the inventory diverge |

## Adding a route

1. Add its `<Route path="...">` to `frontend/src/App.tsx`.
2. Add the same path to `AUDITED_ROUTES` in `routeInventory.ts` with its auth
   class and owning spec (or the peer worker identity).
3. Add its exact cold-mount rows to `routeBudgets.ts` and a focused spec.
4. The parity test fails until the inventory and budget exist.

## Conventions

- Exact counts only; no timings, snapshots, or retry suppression.
- Measure one UI action per window with `perform()` / `navigate()`; never
  assert a whole session as one number.
- `settle()` waits for auth bootstrap, lazy chunk, and three stable request
  turns, so it is deterministic without sleep-based waits.
- Do not add private HTTP caching, feature flags, or disabled tests to make a
  budget pass. Fix the caller or record an allocated shared-file request.
- StrictMode, warm navigation, focus/visibility, redirect, and cross-account
  behavior must remain covered when a budget changes.
