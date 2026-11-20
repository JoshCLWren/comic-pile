# Reading plans and Reading Lists

**Routes:** `/continuity-plans`, `/continuity-plans/new`, `/continuity-plans/:id` for current surfaces. User-visible target semantics follow the [accepted Reading List execution ADR](../READING_LIST_EXECUTION_ADR.md). Agents should test reading intent without depending on retired storage/compiler internals.

## MQA-LIST-001: List editing preserves order and identity

**Setup:** QA-owned custom list.

**Test:** Add, reorder and save known issues; save an unchanged list; reload.

**Expected:** Exact canonical issue IDs/order remain, with no duplicate or unintended addition; an unchanged save doesn't change eligibility or reading state.

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

**Test:** View a thread waiting on a real requirement, read its source issue, and revisit Queue, Roll and list.

**Expected:** Each surface agrees on next unread and eligibility, explains actual named blockers and updates when satisfied.

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

Some currently deployed routes may still implement older Reading Plans behavior. This inventory states intended acceptance criteria for the guarded transition, not a claim that it has already been deployed.
