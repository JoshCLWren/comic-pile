# Comic issue / series cover render-path inventory

Live render-path audit for [#4445](https://github.com/JoshCLWren/comic-pile/issues/4445) (exact-issue actions) and [#5433](https://github.com/JoshCLWren/comic-pile/issues/5433) (covers in every view that references a comic/series). Updated November 26, 2026. **This is an implementation inventory, not proof of production browser acceptance.** Authenticated production QA remains required by #5433 before closure.

## Shared presentation contract

- **Exact owned issue cover/action:** `CompactIssueCardTrigger` (dense rows) and `ComicIssueCard` / `ComicIssueReadingCard` (full action card) render `ComicIssueCover`. Data comes from the owner-scoped `POST /api/v2/issues/cards` batch projection (`useIssueCards`), never per-row provider calls.
- **Series representative cover:** `ComicIssueCover` with `series_cover_image_url` from the threads projection (next unread confirmed issue, fallback first confirmed issue), computed set-based in native SQL.
- **Provider candidate cover (unconfirmed):** `ComicIssueCover` or `ImageWithLoading` with the candidate's own provider image metadata. Never borrow another owned issue's confirmed cover or imply confirmation.
- **No canonical identity:** render text/placeholder without fabricating an issue ID or cover. Historical Session events without canonical issue IDs are a truthful exception.
- **Raw `<img>` is forbidden** outside `frontend/src/components/ImageWithLoading.tsx`; direct owned cover URL bindings to `<img>`/`<ImageWithLoading>` are forbidden outside `ImageWithLoading.tsx` and `ComicIssueCard.tsx`. Enforced by `frontend/src/unit/issue-cover-render-guard.test.ts`.
- **`image_url` is the provider-candidate field, not an owned-cover field.** ComicVine search/import dialogs, Identity Inbox candidates and the Roll modal zoom legitimately bind `image_url` to `ImageWithLoading` for *unconfirmed* provider art (see `ComicVineSearchDialog.tsx`, `AddSeriesFromComicVineDialog.tsx`, `IdentityInboxPage.tsx`, `ComicIdentity.tsx`). The guard intentionally matches only owned-cover fields (`cover_image_url`, `series_cover_image_url`, `coverImageUrl`); raw `<img>` is independently forbidden by the same test, so an owned cover bound through `image_url` to `<ImageWithLoading>` is an accepted, documented gap rather than an owned-confirmation path.

## Exhaustive render-path audit

| Surface | File(s) | Represents | Shared presentation | Data / notes |
|---|---|---|---|---|
| Queue thread rows | `pages/QueuePage/QueueThreadCard.tsx` | Series row / next unread representative | `ComicIssueCover` | `thread.series_cover_image_url` from `/api/v2/threads`; no per-row query. |
| Queue next issue / direct read | `pages/QueuePage/QueueNextIssueCard.tsx`, `components/DirectReadIssuePanel.tsx` | Exact owned issue | `ComicIssueReadingCard` / `ComicIdentity` | Exact issue lookup on demand; owner-scoped issue card batch. |
| Queue issue toggle / reorder | `pages/QueuePage/IssueToggleList.tsx` | Exact owned issues | `CompactIssueCardTrigger` | Bounded displayed IDs batched via parent `useIssueCards`. |
| Roll IN PLAY numbered rows | `pages/RollPage/components/ThreadPool.tsx` | Exact owned issue per die face | `ComicIssueCover` | Existing batched `IssueCardsResponse`; no second per-row request. |
| Roll selected/featured issue | `pages/RollPage/components/ComicIdentity.tsx` | Exact owned issue / provider detail | `ComicIssueCover`, `ImageWithLoading` (modal zoom only) | Provider intelligence query shared by React Query; modal uses shared image component. |
| Roll last read summary | `pages/RollPage/components/LastReadStrip.tsx` | Exact owned issue | `ComicIssueCover` | Cached-only behavior preserved. |
| Roll snoozed shelf | `pages/RollPage/components/ThreadPool.tsx`, `pages/RollPage/resolveSnoozedSeriesCovers.ts` | Series representative | `ComicIssueCover` | Reuses cached thread projections; bounded fetch only when expanded. |
| Roll manual picker | `pages/RollPage/components/ManualPickerSearch.tsx`, `pages/RollPage/manualPickerOptions.ts` | Series representative choice | `ComicIssueCover` | Uses already-fetched thread list / snoozed projections; no per-option request. |
| Roll series history panel | `pages/RollPage/components/SeriesPanel.tsx` | Previous/recent exact owned issues | `ComicIssueCover` | Batched `useIssueCards` for previous/recent issue IDs; no N+1. |
| Roll reading context | `ReadingContextPillar.tsx`, `OptionalReadingCards.tsx`, `ReadingPathPanel.tsx`, `RollRecoveryCard.tsx` | Exact owned issues / prerequisites | `CompactIssueCardTrigger` | Bounded batches; Roll prerequisite switch semantics preserved. |
| Roll decision/rating | `DecisionCard.tsx`, `ComicPillar.tsx` | Exact offered issue | `ComicIssueRatingSlider` / `ComicIssueIdentity` | Roll completion semantics preserved; no direct mutation of pending offer. |
| Thread detail | `pages/ThreadDetailView.tsx` | Exact owned issues | `CompactIssueCardTrigger` | One batch for loaded pages. |
| History | `pages/HistoryPage.tsx` | Exact owned issues when `issue_id` present | `CompactIssueCardTrigger` | Sessionless activity; items without canonical issue ID render no issue action. |
| Session detail | `pages/SessionPage.tsx` | Legacy events | **Exception: text only** | Legacy events carry no trustworthy canonical issue ID; no fabricated cover. |
| Crossovers list/detail | `pages/CrossoversPage.tsx`, `pages/CrossoverDetailPage.tsx` | Exact owned issue members | `CompactIssueCardTrigger` | Batched per visible member IDs. |
| Continuity planner lanes | `pages/continuity-planner/PlannerLanes.tsx` | Owned issue nodes + series/thread nodes | `ComicIssueCover` | Issue nodes use batched issue cards; thread nodes use representative `series_cover_image_url`; crossover/synthetic nodes get no fabricated cover. |
| Continuity plans index | `pages/ContinuityPlansIndexPage.tsx` | Reading plans, not comics | N/A (no comic rows) | Plan cards show plan metadata; no individual comic cover expected. |
| Reading plan detail/reader | `pages/ReadingPlanDetailPage.tsx`, `components/ReaderIssueActions.tsx`, `components/ComicIssueReadingCard.tsx` | Exact owned issues | `CompactIssueCardTrigger` / `ComicIssueReadingCard` | Bounded batch; direct read/rate preserves plan semantics. |
| Reading list editor saved entries | `components/CustomCBLBuilder.tsx`, `components/ReadingListEntryCard.tsx` | Exact owned issues | `ComicIssueCard` | Existing paged `useIssueCards`. |
| Reading list editor search results | `components/CustomCBLBuilder.tsx` | Exact owned issue candidates | `ComicIssueCover` | Batched by visible candidate issue IDs; no draft commit on render. |
| Reading list reader | `components/ReadingListReader.tsx`, `components/ReaderIssueActions.tsx` | Exact owned issues | `CompactIssueCardTrigger` / `ComicIssueReadingCard` | Covered by existing reader components. |
| CBL browser adopted items | `pages/CblBrowserPage.tsx` | Exact owned adopted issues | `CompactIssueCardTrigger` | Provider-only/source-only rows must not invent owned issue identity. |
| CBL source finder owned issue | `components/CblSourceFinder.tsx` | Exact owned issue under inspection | `CompactIssueCardTrigger` | Bounded owner batch for the inspected issue; source rows show source metadata, not fabricated owned covers. |
| Identity inbox candidates | `pages/IdentityInboxPage.tsx` | Unconfirmed provider candidates | `ComicIssueCover` | Candidate-specific provider art from candidate metadata; never borrows confirmed owned cover. |
| Creator detail | `pages/CreatorDetailPage.tsx` | Exact owned issues | `CompactIssueCardTrigger` | Parent batch and on-demand series group batches. |
| Creator comparison | `pages/CreatorComparisonPage.tsx` | Exact owned evidence issues | `CompactIssueCardTrigger` | One owner batch per drilldown. |
| Creator team chemistry | `components/CreatorTeamChemistrySection.tsx` | Exact owned issue refs | `CompactIssueCardTrigger` | Batched rendered match refs. |
| Creator drilldown issue list | `components/DrilldownIssueList.tsx` | Exact owned issues | `CompactIssueCardTrigger` | Bounded batch for rendered drilldown issues. |
| Creators list | `pages/CreatorsPage.tsx` | People, not comics | N/A (no comic rows) | No individual comic cover expected. |
| Dependency builder | `components/DependencyBuilder.tsx`, `components/ReadingOrderTimeline.tsx` | Exact owned issue dependencies / timeline gates | `CompactIssueCardTrigger` (timeline) | Form `<select>` options remain text-only (native control limitation); timeline gates use shared trigger. |
| Reading plan recovery / graph problems | `components/ReadingPlanRecovery.tsx`, `components/ReadingGraphProblemCard.tsx` | Exact owned issues | `CompactIssueCardTrigger` | Batched by visible IDs. |
| Exclusions / eligibility / boundaries | `components/ExclusionExplanation.tsx`, `components/EligibilityExplanation.tsx`, `components/ReadingBoundaryExplanation.tsx` | Exact owned issues when ID present | `CompactIssueCardTrigger` | Fallback named link when no owner card exists. |
| ComicVine search/confirm dialog | `components/ComicVineSearchDialog.tsx` | Provider search results/candidates | `ImageWithLoading` | Provider images are not owned confirmed identities; shared image component prevents bespoke img. |
| Add series from ComicVine dialog | `components/AddSeriesFromComicVineDialog.tsx` | Provider series candidates | `ImageWithLoading` | Provider search/import flow; no owned confirmed cover borrowed. |
| Add to ComicPile dialog | `components/AddToComicPileDialog.tsx` | Provider issue candidate | `ImageWithLoading` | Provider-only issue being added; no owned confirmed cover borrowed. |
| Issue correction dialog | `components/IssueCorrectionDialog.tsx` | Exact owned issue when present | `CompactIssueCardTrigger` | Selected owned issue uses shared covered action trigger; correction preview stays text/metadata. |
| Direct read issue picker | `components/DirectReadIssuePanel.tsx` | Exact owned issues | `ComicIssueReadingCard` / `ComicIssueCover` via shared card | Bounded paginated browse; no per-row provider call. |

## Non-cover / exception surfaces

| Surface | Reason |
|---|---|
| `pages/SessionPage.tsx` legacy events | No trustworthy canonical issue ID; showing guessed cover would be wrong. |
| `pages/ContinuityPlansIndexPage.tsx` | Plan records, not comic/series rows. |
| `pages/CreatorsPage.tsx` | Creator people records, not comic/series rows. |
| Native `<select>` option text in `DependencyBuilder` / `continuity/ComicSelectors` | Browser-native controls cannot render images. |
| Transient copy prompt `pages/RollPage/components/PostRateCopyPrompt.tsx` | Text-only confirmation/copy affordance; no cover data in prompt contract. |

## Verification

- Guard: `frontend/src/unit/issue-cover-render-guard.test.ts` fails on raw `<img>` outside `ImageWithLoading.tsx` and on bespoke cover-src bindings.
- Targeted tests: cover guard, SeriesPanel cover rendering, and existing `ThreadPoolEligibleMappings`, `ManualPickerSearch`, `PlannerLanesCovers`, `IdentityInboxPage`, `CustomCBLBuilder`, `QueueThreadCard` tests.
- Required before closing #5433: authenticated production browser QA (mapped/unmapped, missing image, mobile/zoom), and confirmation that merged deployment SHA is READY on the intended production path.
