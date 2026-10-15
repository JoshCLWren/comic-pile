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

Some currently deployed routes may still implement older Reading Plans behavior. This inventory states intended acceptance criteria for the guarded transition, not a claim that it has already been deployed.
