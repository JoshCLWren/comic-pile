# CBL browser

**Route:** `/cbl-sources`. Discover, preview and adopt external Comic Book Reading List sources into reader-owned lists.

## MQA-CBL-001: Browse/search truthfully

**Test:** Browse available sources and search a recognizable source, inspecting suggestion and result relevance.

**Expected:** Matching lists can be found where available, suggestions correspond to the query, and missing sources are not claimed to exist.

## MQA-CBL-002: Preview is non-mutating

**Test:** Open a source preview and compare entry sequence and proposed changes with an existing QA list.

**Expected:** Issues, order, unmapped entries and proposed changes are clear; preview alone does not alter owned lists or reading state.

## MQA-CBL-003: Adoption preserves curated intent

**Setup:** QA-owned list with deliberately curated issue order.

**Test:** Approve an import/update and revisit this and unrelated lists.

**Expected:** Only the approved changes occur; no unrelated order, excluded comic or list is silently regenerated, replaced or added.

**Atomic adoption and retry safety (owner clarification 2026-11-20):** A large import either commits **all** approved entries and membership changes atomically or leaves the old list unchanged, with truthful errors. After an ambiguous network timeout, the browser-only QA tester reloads and verifies the resulting list before retrying: exactly one complete approved import or an unchanged list, never a partial list or duplicate membership. The backend must reconcile authoritative adoption receipts/idempotency on retries. Do not treat partially adopted items as acceptable success. Tracked by [#5522](https://github.com/JoshCLWren/comic-pile/issues/5522).

## MQA-CBL-004: Imported lists agree with Roll rules

**Test:** Inspect a QA list with known strict/loose gates after the Reading List model is active and compare Roll offers.

**Expected:** Result honors the list's actual gates and prerequisites; ordinary loose-list adjacency is never silently compiled into hard blocks. **Only Option E Reading Lists determine execution**. Old continuity-plan detail pages and dependency rows cannot declare an unread issue available, blocked, or eligible by inventing a second evaluator. Test the actual canonical list frontier, overlap constraints, holds, exclusions, and prerequisites; orphaned/legacy Plan display retirement belongs to [#3678](https://github.com/JoshCLWren/comic-pile/issues/3678).

## MQA-CBL-005: Same-name adoption cannot overwrite an existing list

**Setup:** QA-owned curated list named Alpha Flight with 228 distinct ordered entries, and an available CBL source also titled Alpha Flight.

**Test:** Preview the matching CBL, deliberately deselect one source issue/series, click Add this reading order, and inspect the existing list and any new/updated list. Repeat through cancel, error, and an explicitly selected update path if offered.

**Expected:** The existing list is never implicitly selected for replacement by title alone. A name collision is clearly disambiguated, using a new distinct list name/identity or an explicit confirmation to update a specified existing list with a full change preview. Cancel and failed writes do not mutate either list. Only explicitly approved entries change; previously curated ordering, exclusions, IDs, read states and unrelated lists remain intact. Deleting a newly imported list cannot reveal that a prior same-named list was silently destroyed.

**Tracking:** Reproduced QA data-loss issue [#3933](https://github.com/JoshCLWren/comic-pile/issues/3933). The expected safety rule is independent of whether its current implementation has shipped.

## MQA-CBL-006: Out-of-range browse pages clamp to the last page

**Test:** Request a catalog browse/search page beyond the last page.

**Expected:** The last valid page's matching results are returned instead of a false empty state. Source: #5381, fixed by #5445.

## MQA-CBL-007: Cycle-only previews show the loop and a resolve path

**Setup:** CBL preview whose reading graph has a cycle but no overlap questions.

**Test:** Preview it and try Add.

**Expected:** Add is disabled with a reason, the reading-graph panel shows the loop and series graph, and a hint explains how to break it (exclude a series in the loop under Customize). Source: #5379, fixed by #5438.
