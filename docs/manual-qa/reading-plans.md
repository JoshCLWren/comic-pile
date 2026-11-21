# Reading plans and Reading Lists

**Execution authority (owner decision 2026-11-20):** Option E is the **only** reading execution model. Its reader-owned Reading Lists are canonical; `strict` and `loose` are **modes of a Reading List**, not separate types of Reading Plans. The `/continuity-plans`, `/continuity-plans/new`, `/continuity-plans/:id` and editor routes are legacy transition/retirement surfaces, **not** feature targets. Follow the [accepted Reading List execution ADR](../READING_LIST_EXECUTION_ADR.md) and retirement [#3678](https://github.com/JoshCLWren/comic-pile/issues/3678). Verify preserved issue IDs, list ordering, gates, prerequisites, exclusions, read/rating history, and deep links on migration. Never report a defect solely because an obsolete Plan editor does not support new authoring.

## MQA-LIST-001: List editing preserves order and identity

**Setup:** QA-owned custom list.

**Test:** Add, reorder and save known issues; save an unchanged list; reload.

**Expected:** Exact canonical issue IDs/order remain, with no duplicate or unintended addition; an unchanged save doesn't change eligibility or reading state.

**Issue search (owner issue #4725):** Searching the Reading List editor for an issue (e.g. `Mutant X #1`) lists each canonical issue once; the database already forbids a duplicate issue number within one series, so the only look-alike rows are distinct series sharing a title. Those stay separate rows (the editor groups them by series) and show a `Series ID` label so they can be told apart. Search deliberately remains click/Enter-driven ("Find issues"): live as-you-type suggestions are not offered, to avoid one request per keystroke against the issue table; revisit only with debounced, cancelled requests. Each result now displays the exact owned issue cover from one bounded batch, or the shared placeholder. Adding a result does not commit an unsaved list or mutate reading state; keyboard focus and duplicate-series disambiguation remain correct.

**Reading List cover check (#5433):** In the authoritative Reading List editor, mapped issues with available covers use the shared issue-cover component and the exact owned Issue identity. Unmapped issues show the shared placeholder. A conceptual crossover marker must never fabricate an issue cover. Reordering and Save preserve list membership, stable IDs, and Option E gates; do **not** resurrect the old continuity-plan editor, lanes, or compiler to satisfy image coverage.

## MQA-LIST-002: Strict means earlier remaining entries first

**Setup:** Strict QA list interleaving multiple series and a curated later annual.

**Test:** Check Roll before/after reading preceding list entries.

**Expected:** Later included entries wait for all earlier unread included entries. Annual position is respected.

## MQA-LIST-003: Loose allows independent progression

**Setup:** Loose QA list with neighboring issues in different series but no gate.

**Test:** Read further in one series without adjacent other-series issues.

**Expected:** Ordinary loose adjacency never blocks; only explicit gates, prerequisites and other active blockers restrict selection.

## MQA-LIST-004: Hold, after-previous and explicit prerequisite

**Setup:** QA list with those gates and an independent issue prerequisite.

**Test:** Observe blockers before/after reading sources; reorder an after-previous item.

**Expected:** Only intended named issue requirements block. Changed predecessor requires confirmation; explicit prerequisite survives reorder or list deletion. Labels like Annual don't create inferred requirements.

## MQA-LIST-005: Overlapping lists share one read state

**Setup:** Same QA issue belongs to multiple lists with distinct constraints.

**Test:** Mark the issue read through one context and revisit both lists and Roll.

**Expected:** There is one global read state; all active list and explicit prerequisites combine, and a loose list cannot cancel a strict blocker.

## MQA-LIST-006: Eligibility explanations agree

**Owner ruling (2026-10-14, [#3636 comment](https://github.com/JoshCLWren/comic-pile/issues/3636#issuecomment-6174141373)):** a dependency may be described from both ends -- "Young Justice blocked by Hourman #9" and "Hourman blocking Young Justice #16" are the source and dependent of one prerequisite and legitimately name different issue numbers. Do not change edges or labels to make the numbers equal; flag only if an endpoint is not actually related.

**Test:** View a thread waiting on a real requirement, read its source issue, and revisit Queue, Roll and list.

**Expected:** Each surface agrees on next unread and eligibility, explains actual named blockers and updates when satisfied.

**Authority check:** Derive eligibility only from the Option E evaluator and its active Reading Lists, natural series position, explicit reader prerequisites, holds, and exclusions. An unread issue is **not automatically available** merely because a retired Plan detail screen names no legacy blocker; strict order, loose-list gates, overlapping lists and frontier position all matter. Never derive availability from legacy Plan order, `reading_plan_dependencies`, or compiled edges. QA case [#5622](https://github.com/JoshCLWren/comic-pile/issues/5622) exposed contradictory old-plan copy; its proposed legacy eligibility implementation [PR #5627](https://github.com/JoshCLWren/comic-pile/pull/5627) conflicts with this contract.

## MQA-LIST-007: Durable exclusion versus local skip

**Setup:** QA-excluded series, plus a separate locally skipped issue.

**Test:** Edit/reimport a list and revisit Roll/CBL; inspect the locally skipped issue.

**Expected:** Globally excluded material stays excluded until expressly restored. List-local skip does not globally hide its issue. No implicit recreation of intentionally excluded material.

## MQA-LIST-008: Explicit overlap exceptions are narrow and durable

**Setup:** A strict QA list containing two overlapping ComicVine volumes plus a third series, an explicit prerequisite, and a hold/after-previous gate.

**Test:** Explicitly approve one volume continuing while the other waits; inspect the preview and persisted rule, roll both volumes, then compare a same-titled different volume and another list.

**Expected:** Only the exact reader-approved pair of ComicVine series/volume identities relaxes implicit cross-volume strict adjacency. Both retain their own issue order; the waiting volume is not marked read or skipped. Explicit prerequisites, hold/after-previous gates, other lists, third series, and ambiguous or different volumes still block normally. Preview and saved eligibility agree; the exception survives reloading the list. The reader can revoke the exception without changing read history.

## MQA-LIST-009: Reader selects whole series or individual issues in overlaps

**Setup:** A QA reading order with several overlapping series/volumes and multiple candidate issues each.

**Test:** Open the reading-order creation/editing selection flow; inspect defaults; deselect a whole series, reselect it, deselect individual overlapping issues, save, and reopen. Repeat against an already-owned matching list.

**Expected:** Inclusion checkboxes start selected for all offered series and issues. The reader can choose all, some or none of a series through a series-level checkbox and granular issue checkboxes, with clear mixed-selection feedback. Unchecked selections are deliberately omitted only from that list/overlap selection and do not mark comics globally excluded or read. Saving updates the intended existing list/selection (upsert), using stable canonical issue and ComicVine volume identity, without creating duplicate membership or replacing unrelated lists. No issue is silently included after the reader unchecked it.

## MQA-LIST-010: Editing constraints fails closed on conflicts

**Setup:** Multiple QA lists sharing issues and explicit prerequisites; include a partially represented Thread and a possible three-list/series cycle.

**Test:** Save an unchanged list, reorder an after-previous entry to change its predecessor, intentionally create a cross-list cycle, and modify inclusion to omit unread issues from a partly represented Thread.

**Expected:** Unchanged save is idempotent. A changed after-previous target requires explicit visible confirmation naming the new predecessor. A cycle or stranded prerequisite is rejected atomically with a human-readable path/provenance, not a partial write. Partial Thread inclusion triggers a clear warning rather than silently assuming missing issues are gated. Invalid or canceled changes preserve the prior valid list and read state.

**Authority:** [Reading List execution ADR](../READING_LIST_EXECUTION_ADR.md), with the owner-approved series/issue selection design. The checkbox selection controls list membership; the separate overlap exception changes strict eligibility only for an explicitly approved pair.

Some deployed legacy Plan pages may still exist pending the safe, gated retirement in #3678. Test them for data preservation, secure migration/redirects, truthful diagnostics, and noninterference with Option E, **not** as a competing execution model. Do not reopen or extend old Plan authoring/eligibility code.

## MQA-LIST-011: An empty Reading Plan can be opened and edited

**Status: Retired (2026-11-20).** The old zero-lane Reading Plan creation/editor requirement was superseded by the owner's Option E-only decision. Legacy Plan UI is being safely retired in #3678; see #5614.

**Test:** Create a plan with no lanes and no steps, save, then open it from the plans list and reload. Add an issue with the legacy editor, save, and reopen both the detail page and the edit route. For a plan whose Reading List was removed, open the recovery screen and click "open the Plan authoring UI".

**Expected:** The saved plan opens as an empty plan (not a 409 recovery screen) and can be edited. Adding an issue does not strand it: the reopened detail page shows the authored issue and the editor still opens. The recovery authoring link opens that saved plan's editor, not an authority error and not a blank new plan. Source: [#5462](https://github.com/JoshCLWren/comic-pile/issues/5462).

## MQA-LIST-012: Orphaned plans recover only through explicit preview and relink

**Status: Retired (2026-11-20).** Orphaned legacy Plan recovery UI is retirement/migration work, not a supported parallel authoring flow. See owner contract #3678.

**Setup:** QA plan whose Reading List identity was deleted.

**Test:** Open the plan, review the recovery diff, then explicitly relink.

**Expected:** The reader sees a preview of surviving issue references and chooses the relink; nothing is relinked automatically, and other owners' lists are never targets. Source: #4684 (Nov 5 recovery work).

## MQA-LIST-013: Dependency cycles are contained, not outages

**Test:** Attempt a list edit or CBL adoption that would create a prerequisite cycle.

**Expected:** The write fails closed with a clear message before any change is committed; Roll and Queue remain usable. Source: P0 #4759.

## MQA-LIST-014: Displayed plan reading mode survives refresh and recovery

**Status: Retired (2026-11-20).** Legacy `strict_sequential`/`informational` Plan presentation is not an independent execution mode. Strict/loose are canonical Reading List modes. See #3678.

**Setup:** A saved Strict (`strict_sequential`) Reading Plan, including one linked to a Loose (`loose`) authoritative Reading List and one that never had a List link.

**Test:** Open the plan detail page, refresh it, and reopen it after an orphaned-plan recovery relink. Compare the eyebrow mode label with the plans index and the planner editor.

**Expected:** Every surface shows Strict for a plan saved as Strict; a missing, stale or Loose authoritative List never silently downgrades the displayed mode to Informational. The linked Reading List remains the sole authority for actual availability, blockers and explanations (MQA-LIST-002/003), so a mode change is only ever the result of an explicit save or relink choice, never a refresh-time projection. Source: #4724 (post-Rust QA follow-up to #4684).

## MQA-PLAN-SYNC: Open plan detail follows a thread rename from another tab

**Status: Retired (2026-11-20).** The immediate-focus expectation for the obsolete Plan detail page was withdrawn; canonical Reading List cross-tab updates may take a short automatic delay. See #5615 and #3678.

**Test:** Open a plan detail and a thread detail in separate tabs. Rename the thread in the thread tab, then switch back to the plan tab without reloading.

**Expected:** The plan detail shows the new series title as soon as the tab regains focus, with no reload. Source: #5486 (part of #5264); related MQA-QUEUE-010.

## MQA-LIST-015: Empty authoritative Reading List creation is safe

**Test:** In the current Reading List editor, create an empty reader-owned Reading List in strict or loose mode. Save and reload. If empty lists are not supported, verify the UI explains the requirement **before submission**. Add a real owned issue and reopen the list.

**Expected:** Supported empty lists persist without fictitious issue membership; otherwise invalid saves produce a clear, actionable validation message and no partial write. Adding a selected issue to an existing list persists its stable Issue ID, order and mode without changing read history. **Do not test `/continuity-plans/new`, zero-lane creation, legacy plan editors, or orphaned-plan authoring links as supported feature flows.** Their retirement/deep-link migration belongs to #3678. Historical report [#5614](https://github.com/JoshCLWren/comic-pile/issues/5614) was superseded by owner decision 2026-11-20; earlier #5462 behavior is transition-only.

## MQA-LIST-016: Legacy Plan deep links migrate safely to canonical Reading Lists

**Setup:** A historical Plan deep link with retained source information, including a case whose previously linked Reading List was deleted or is ambiguous.

**Test:** Open the old deep link after the authoritative Reading List experience has replaced it. Inspect any migration/recovery preview, whether the target list identity is verified, and whether an explicit relink is required. Confirm preserved authored sequence and history.

**Expected:** Verified links redirect to the correct owner-scoped Reading List. Ambiguous or orphaned links explain the situation, preview surviving stable issue references and ask for an **explicit reader-approved** relink before any write. Never auto-create a competing legacy Plan, silently select someone else's list, fabricate eligibility, or discard read/rating/issue state. Tracking: retirement #3678; historical recovery #4684.

## MQA-LIST-017: Canonical Reading List mode survives refresh and safe migration

**Setup:** A strict authoritative Reading List and a loose authoritative Reading List. Include an old saved Plan that had a contradictory display-mode field, if legacy deep links still exist.

**Test:** Open the authoritative list, reload and navigate away/back; follow any supported old Plan deep-link redirect or explicit migration/relink, and compare the visible mode with actual Option E Roll/Queue eligibility.

**Expected:** The visible strict/loose mode is the **saved canonical Reading List mode**, not an obsolete `strict_sequential`/`informational` Plan label. A legacy Plan's old mode must never silently override the linked List or create a second eligibility source. Explicit list-mode edits persist; strict/loose evaluation, blockers and explanations agree everywhere. Historical #4724 was legacy presentation compatibility, not permission to preserve parallel Plan execution.

## MQA-LIST-018: Reading List titles refresh after cross-tab rename

**Test:** Open an authoritative Reading List and its Thread detail in separate tabs. Rename the Thread, then return to the Reading List tab without manually reloading.

**Expected:** The Reading List displays the canonical updated series title after a **short automatic refresh delay**; it need not update synchronously on focus. No prolonged stale state, manual hard refresh, or mutated list membership. Any remaining old Plan deep links follow the migration rules in #3678. Owner decision 2026-11-20; source #5486 (part of #5264).
