# App-wide comic issue-card mount-point inventory

Live implementation audit for [#4445](https://github.com/JoshCLWren/comic-pile/issues/4445), parent #4442. Updated November 7, 2026. **This is an implementation checklist, not a claim that the app-wide contract is complete.**

## Canonical contract

Exact owned `issue_id` is the only key for the owner-scoped `POST /api/v2/issues/cards` projection: `issue_id`, thread, exact issue number, status, saved rating, confirmed ComicVine mapping and **issue-specific** CDN cover. In sparse UI, `CompactIssueCardTrigger` renders `ComicIssueCover` and opens the **same** `ComicIssueCard` and native direct read/rating/map actions. A thread, series, provider-only item, aggregate or history event without exact owned issue identity is *not* a valid owned issue card.

Existing `useIssueCards` batches visible owned IDs (up to 200 per request), not one request per row. The compact trigger fetches an individual projection **only on user expansion if no parent batch card is available**. The normal `ComicIssueCard` owns the full direct actions. Read/rate must neither bypass ownership nor mutate Roll pending selection/die/queue. The actual Roll-offer completion workflow retains its special die and queue effects.

## Live mount-point audit

| # | Source and rendered issue identity | Covered action today | Data/coverage evidence | Remaining action |
|---|---|---|---|---|
| 1 | `ReadingListReader.tsx`: owned canonical issue ID per list row | Existing `ComicIssueCard` | Parent `useIssueCards`, `ReadingListReader.test.tsx` | Verify hold/blocked/excluded in authenticated QA |
| 2 | `ReadingPlanDetailPage.tsx`: canonical issue IDs and blocker IDs | Existing `ReaderIssueActions` with `ComicIssueCard`; blockers routed via shared boundary UI where possible | Parent `useIssueCards`, `ReadingPlanDetailPage` tests | Header `Read next` has no covered trigger; confirm blocker lanes |
| 3 | `CustomCBLBuilder.tsx`, `ReadingListEntryCard.tsx`: canonical list entries | Existing `ComicIssueCard` and compact controls | Paged `useIssueCards`, `CustomCBLBuilder.test.tsx` | Audit search selection and live draft-mode side effects |
| 4 | `CblSourceFinder.tsx` and CBL catalog search/preview | Finder has exact owned `issueId` in `CblComicFinder`, but source-only CBL refs may not resolve to owned issues | Source lookups, not necessarily one canonical owned ID per item | Add covered trigger only to matched owned item rows; provider-only item needs correct independent artwork/add |
| 5 | `EligibilityExplanation.tsx`, `ReadingBoundaryExplanation.tsx`: dependency ID or explicit boundary owned issue ID | **This PR**: batched compact covered action when owner card exists; fallback named link otherwise | `useIssueCards`, existing explanation tests | QA view of strict named prerequisites |
| 6 | `ThreadDetailView.tsx`: canonical IDs on paged Thread issues, including deep link | **This PR**: replaces independent `IssueRateButton` / `IssueReadStatusButton` with shared trigger and cover | One batch for loaded pages; Thread detail tests and compact trigger tests | Verify exact-focus behavior, creators/tags, stale cache |
| 7 | `QueueThreadCard.tsx`: series summary often has only `next_unread_issue_number`, no canonical next `issue_id` | No issue card for thread-only row (correctly avoids guessing an issue) | Queue list schema explicitly omits `next_unread_issue_id` | Add real next canonical issue ID to Queue projection or resolve on expansion; only then render issue card |
| 8 | `IssueToggleList.tsx`: exact IDs for issue pills and reorder rows (Queue and Thread Edit Series) | **This PR**: compact trigger independent of reorder/delete and staged draft operations | Bounded displayed IDs; callback preserves staged edits | QA deferred Edit Series/drag/undo/scroll |
| 9 | `IssueList.tsx`, `IssueCorrectionDialog.tsx` | Not inventoried as active issuer yet | Need call-site search to distinguish live and dead components | If live and exact selected owner ID, compose trigger; remove genuinely dead variants |
| 10 | Manual pickers and Queue actions | Roll option may have only thread ID, not exact owned issue ID | `manualPickerOptions.ts`, Queue mutation UI | Preserve thread-only choice; offer direct card for canonical issue picker, never invent |
| 11 | `RatingView.tsx`, `ComicPillar.tsx`, `ComicIdentity.tsx`, `DecisionCard.tsx` | Roll offer retains specialised completion, reuses shared rating slider; **this PR** shares owned issue triggers in `ComicIdentity` related arcs | `useComicVineIssueIntelligence`, Roll tests | Unify featured cover/identity presentation without disrupting offered-comic effects, zoom or mapping |
| 12 | `OptionalReadingCards.tsx`, `ReadingContextPillar.tsx`, `ReadingPathPanel.tsx`: exact local-chain/continuity IDs | **This PR**: shared compact covered actions on owned nearby issue refs, exclusions for active current Roll offer and unknown ids | Batched `useIssueCards` (local chain and edges), existing Roll context tests | QA continuity and mobile layout |
| 13 | `RollRecoveryCard.tsx`, `ReadingOrderGroups.tsx`, `ReadingRouteExplanation.tsx`, `ReadingOrderTimeline.tsx`, `DependencyBuilder.tsx` | Canonical refs vary by API; many are synthetic/group/thread-only | Recovery and timeline source contracts | Audit exact ID-bearing leaves, add trigger only for owner IDs |
| 14 | `ComicIdentity.tsx`, `ComicVineIssueCard.tsx` related story arcs | **This PR**: confirmed owned `comicpile_matches.issue_id` get shared trigger; missing provider issues retain Add flow | Nested owner-scoped batch; provider item has no direct cover field | Supply proper *related issue* provider art for missing entries; never borrow current Roll cover |
| 15 | `CreatorDetailPage.tsx`: rated, upcoming, read-unrated and insight rows | **This PR**: shared trigger and cover, including expanded series | One parent batch and one per on-demand series group; existing creator tests | Verify ratings invalidation and link/a11y parity |
| 16 | `CreatorComparisonPage.tsx`, `DrilldownIssueList.tsx`: evidence exact IDs | **This PR**: shared trigger and cover, existing named deep link maintained | One owner batch per drilldown | Verify evidence counts/statistics unchanged |
| 17 | `CreatorTeamChemistrySection.tsx`: `shared_issue_refs.issue_id` | **This PR**: shared compact cards for owner refs | One batch for rendered matches | Verify creator team ref labels / mobile flow |
| 18 | `HistoryPage.tsx` (session summaries), `SessionPage.tsx` (legacy events) | **Not yet**: current event projections often have thread ID + issue number but *not canonical issue ID* | Legacy session `DisplayEvent` contains issue_number but no owned issue_id | Add canonical ID to new sessionless activity projection; no guessed ID for legacy/deleted events |
| 19 | Other issue-search, crossover and import previews | Some still render exact owned issue IDs outside the above components | Need JSX search and route call-site inventory | Wire exact owner refs and provider-only add/maps; do not render a card for aggregates |
| 20 | Popovers/inline dense rows | **This PR**: `CompactIssueCardTrigger` with covered touch target opens full shared action card | `CompactIssueCardTrigger.test.tsx` | Mobile accessibility, drag/menu nesting and visual density QA |

## Required verification before closing #4445

- CI: exact-head frontend lint + typecheck, Vitest with original thresholds, Rust/auth/backend checks, Chromium audit; independent review of changes.
- Reader QA: Mignolaverse strict blocker, a comic present in Plan/List/Thread/Queue/creator evidence, rating correction from each, later #10 ahead of #2, held/inactive/excluded/read, active Roll pending selection unaffected by manual action.
- Asset QA: issue #1 and #2 use distinct correct ComicVine URLs; image failure never disables direct read; provider-only issue never inherits cover of the active Roll offer.
- Performance: 400+ CBL/Thread page uses bounded owner-card metadata lookup, lazy art, not per-row provider calls.
- History: only canonical exact owned IDs are actionable; no fabricated references.
- Confirm merged deployment SHA is READY and mapped to `comic-pile.vercel.app` after login-based browser acceptance.

**Do not close #4445 or parent #4442 until every applicable live mount is complete.**
