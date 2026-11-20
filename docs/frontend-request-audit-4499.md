# Frontend request-efficiency audit — parent #4499

View-by-view before/after matrix for the repo-wide duplicate/unused API
request audit. Scope is every route in `frontend/src/App.tsx`, including
overlays, tabs, and the shared authenticated shell. The CI inventory guard
(`frontend/src/test/network-budget/routeInventory.test.ts`) fails when
`App.tsx` and the audited route table diverge, or when any inventoried route
does not name an existing request-budget spec.

Child delivery: #4501 authenticated core (PR #4508), #4502 creator/discovery
(PR #4511, #4609), #4503 reading/continuity/identity (PR #4506), #4504
public/auxiliary + CI guard (PR #4509, #4619). PR #4500 (deferred eager team
chemistry) is one narrow fix, not completion of this parent.

Counts are exact axios-transport rows (`METHOD /api/path?sorted-query xCOUNT`)
on a cold mount unless noted. Warm-remount, StrictMode, focus/visibility,
and mutation-refresh behavior are covered by the specs listed per row.

## Authenticated primary

| Route | Action | Before | After | Cause | Fix |
| --- | --- | --- | --- | --- | --- |
| `/` (Roll) | Cold load | 1 bootstrap read | 1 (required) | — | #4501 budget preserved |
| `/queue` | Cold load | 6 reads | 6 (each feeds rendered row/count/state) | — | #4501 budget preserved |
| `/queue` | Search `r→ro→…→robert` | intermediate requests | 1 final-value request | debounce commits once | #4501 |
| `/thread/:id` | Cold load, canonical evaluator available | 6 reads | **5** | closed `TagEditor` fetched tag catalog before its open gate | #4508: `useTags` enabled scope |
| `/thread/:id` | Cold load, evaluator unavailable | 7 reads | **6** | same | #4508 |
| `/thread/:id` | Crossover groups | serial after thread detail | parallel with detail | keyed on loaded record | #4508: keyed on route id |
| `/history` | Cold load | 1 session-list page | 1 (required) | — | #4501 budget preserved |
| `/sessions/:id` | Cold load | details + snapshots | 2 (required) | — | #4501 budget preserved |
| Auth shell | Mount | prefs + identity-inbox badge | 1 each (required) | — | #4501 |

## Creator / discovery / crossovers / CBL

| Route | Action | Before | After | Cause | Fix |
| --- | --- | --- | --- | --- | --- |
| `/creators` | Cold load | 1 list read | 1; superseded searches abort | stale in-flight search | #4511 + staleTime/gcTime (#4609) |
| `/creators/:creatorKey` | Cold load | 2 reads (detail + team chemistry) | **1** | eager team-chemistry fetch | #4500/#4511: deferred to disclosure |
| `/creators/compare` | Cold load | 1 deduped key-set read | 1 (required) | — | #4511 |
| `/crossovers`, `/crossovers/:group` | Cold load | 2 reads (groups + full thread enumeration) | **1** | eager enumeration | #4511: enumerated on expansion only |
| `/crossovers` | Direct visit | redirect | redirect to continuity plans/events | legacy alias | `unit/App.test.tsx` |
| `/cbl-sources` | Cold root browse | root + detail/preview/graph reads | **1** (root only) | premature detail reads | #4511 |

## Reading / continuity / identity

| Route | Action | Before | After | Cause | Fix |
| --- | --- | --- | --- | --- | --- |
| `/identity-inbox` | Cold load | 2 (badge probe `limit=1` + page `limit=20`) | **1** (shared page query) | duplicate badge probe | #4506 |
| `/identity-inbox` | Confirm/reject candidate | stale badge | page + badge refresh from one shared query | separate badge cache | #4506 |
| `/continuity-plans` | Cold load / warm remount | 1 list read / refetch | 1 / 0 | — | #4503 |
| `/continuity-plans/new` | Cold load | threads + groups once | once (required) | — | #4503 |
| `/continuity-plans/events` | Cold load | groups only until expanded | groups only | enumeration deferred | #4503 |
| `/continuity-plans/:id` | Cold load | reader + tags once; closed editor added catalog read | reader + tags once; closed editor **0** | same `TagEditor` gate as Thread | #4506/#4508 |
| `/continuity-plans/:id/edit` | Cold load (legacy edit) | plan + planner collections + tags once | once each | — | #4503 |
| `/reading-lists/:id` | Cold load | list index + selected list once | once each | — | #4503 |

## Public and auxiliary

| Route | Action | Before | After | Cause | Fix |
| --- | --- | --- | --- | --- | --- |
| `/login`, `/register` | Cookieless cold load | auth probe (me + refresh) | **0** | probe before public form | #4509: no-token fast path |
| `/forgot-password`, `/reset-password` | Cookieless cold load | 2 (me + failed refresh) | **0** | same | #4509 |
| `/demo` | Cold load | probe + demo roll | 3 (probe + `GET /api/v1/demo/roll`, required) | — | #4509 budget |
| `/` (guest), `*` (unknown), `/rate`, `/analytics`, `/roll` | Cold load | 2 (me + refresh) | 2 (required; guest has no session to validate) | — | #4509 budget |
| `/whats-new` | Cold load | shell + releases page | 4 (required) | — | #4509 budget |
| `/glossary`, `/help` → `/glossary` | Cold load | shell only | 3 (required) | redirect does not duplicate shell reads | #4509 budget |
| Cross-account | Logout/login | — | releases refetched; no cross-account cache leakage | session cache cleared | #4509 `authTransitions` spec |

## Remaining before parent closure

- **Production-path verification** after deploy for representative journeys
  (Roll, Queue, Thread, creator, continuity, public/auth). Local and CI
  evidence above does not substitute for deployed proof.
- **Queue canonical + legacy blocking double batch** in Option-E-off
  deployments: needs a server capability signal; tracked under #4501.
- **Authenticated shell remount on navigation**: an `App.tsx` layout change;
  allocated to the coordinator, not claimed here.
- **Owner pause**: #4501 is parked `blocked` pending owner instruction for
  the review/merge/deploy path. This parent stays open until the items
  above are verified; no child merge closes it.

No broad private-data HTTP caching, feature flags, shadow modes, or disabled
tests were introduced to make any budget pass.
