# Navigation and page entry points

Issue #5437 requires every routed page to be reachable from navigation or a
documented entry point, with no page or endpoint left without a caller. The
top-level navigation intentionally stays compact; these are the decided entry
points for pages that are not direct nav items.

| Route | Entry point | Decision |
| --- | --- | --- |
| `/crossovers` | `Reading plans` nav item → `/continuity-plans` (the legacy URL redirects there; `?group=` deep links go to `/continuity-plans/events`) | Crossovers was demoted from top-level nav and kept as a discovery sub-view under Reading Plans in #3488. The duplicate crossover order UI was removed in #3301. Do not re-add a competing nav item. |
| `/crossovers/:group` | `/continuity-plans/events` (Crossover events) and continuity/crossover detail links | Detail deep links stay routable; the list view above is the discovery surface. |
| `/cbl-sources` | The CBL browser button on the Reading Plans index (`ContinuityPlansIndexPage`) and links in the CBL comparison/source panels | CBL sources are a Reading Plans authoring tool, not a top-level browse destination. The page is reachable from that flow; no separate primary nav item. |
| `/analytics` | Redirect to `/` only | The orphaned Analytics page was deleted in #5446 and its uncalled `GET /api/v2/analytics/metrics` endpoint was retired in this slice. Old bookmarks still land on Roll. |
| `/sessions/:id` | Session detail links from History | The timeline was fixed in #5416; reachability from History is tracked in #5387. Session detail may be retired with sessionless Roll (#4405). |

## Tags

There is no `/tags` route. Tags are managed where they are used: dialogs on
thread and issue views support adding, removing and colouring tags. A dedicated
Tags page (global usage counts, rename/merge/color/delete, links to tagged
items) is deliberately **not** added in this slice. The ComicVine-derived tag
inventory and the tag-versus-facet decision are an owner decision in #5436,
which is marked `factory-execution:manual-only`; a Tags page built before that
decision would bake in the wrong data model. The dialogs are the documented
entry point until #5436 is resolved.

## Route inventory

`frontend/src/test/network-budget/routeInventory.ts` mirrors the literal
`<Route path="...">` entries in `App.tsx`. These decisions add and remove no
frontend routes, so that inventory and its request-budget specs are unchanged.
Backend route fragments, the OpenAPI contract and the generated client are
updated in the same slice that retires the analytics endpoint.
