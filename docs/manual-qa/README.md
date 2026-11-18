# ComicPile manual QA inventory

This is the inventory of **what agents should exercise in ComicPile and how the application is intended to behave**. It contains existing workflows and owner-confirmed behaviors that may not be implemented yet. It is not a status board, an execution log, an issue queue, or a schedule.

Each scenario has a stable `MQA-*` ID, prerequisites when needed, concrete actions, and expected results. **Expected behavior is the contract**, even when the current implementation disagrees. Do not silently weaken a requirement just to make the current code pass.

## How an agent uses it

1. Read the applicable feature document and execute the steps through the real application, not merely by reading source code.
2. For changes to comics, issues, ratings, mappings, or tags, use the dedicated QA account in production with QA-owned fixtures, never the owner's collection.
3. Compare actual behavior with every expected result. Capture useful evidence in the agent's findings or linked GitHub issue. **Do not put pass/fail or implementation status labels into this inventory.** A green CI check or merged PR is not a manual QA result.
4. Reconcile any observed failure against existing GitHub issues/PRs and investigate the root cause before opening a new issue. Never open one issue per failed assertion automatically. Retest a fixed behavior without deleting the scenario.
5. Maintain these expected workflows when a product decision changes. Keep scenario IDs stable and do not treat the absence of a future feature as evidence that its requirement was abandoned.

The separate [E2E behavior inventory](../e2e-behavior-inventory.yaml) tracks automated browser regression coverage. This inventory serves human or browser-operating agents doing manual QA. **QA scheduling is outside this inventory.**

## Features

| Document | What to exercise |
| --- | --- |
| [Roll](roll.md) | Die ladder d2-d20, ratings, undo, immediate repeat prevention, uniform selection, reroll snoozes, pending roll |
| [Queue](queue.md) | Durable order, blocked state, snooze, eligibility, mapping health |
| [Queue ComicVine mapping](queue-mapping.md) | Volume search, safe mapping, full and partial unmapped repair |
| [Thread detail](thread-detail.md) | Issue order, read state, ratings, identity |
| [Tags](tags.md) | Creation, reuse, color, bulk application, inheritance (no standalone Tags page: retired 2026-11-18) |
| [Reading plans and lists](reading-plans.md) | Ordering, strict/loose, prerequisites, exclusions, overlap |
| [CBL browser](cbl-browser.md) | Source discovery, preview, adoption |
| [Identity inbox](identity-inbox.md) | Review and correct canonical identities |
| [Creators](creators.md) | Counts, drill-down, comparison |
| [History](history.md) | Recorded reading and roll events |
| [Sessions](sessions.md) | Reading sessions and pending choices |
| [Analytics](analytics.md) | Retired 2026-11-18 (page deleted; only the bookmark redirect remains) |

**Explicitly excluded:** Crossovers is a retired feature. Its obsolete page is not an acceptance target; reading-order behavior now belongs in Reading Lists.

## Provenance

Derived from the owner's October 15, 2026 14-file behavior catalogue and confirmed expectations. Prior dated observations from that ZIP informed scenarios but do not establish current passing tests. The ZIP's daily-rotation references, status/stub labels, and stale assertions have been removed.
## Maintenance rule (added 2026-11-18)

- Every PR that changes user-facing behavior (UI, routes, copy, eligibility, die/queue rules, API behavior a reader sees) must update the affected `MQA-*` scenarios in the same PR, or cite the IDs it affects and say "contract unchanged" in the PR description. If no scenario covers the behavior, add one with the next free ID.
- Only an owner decision (issue/PR comment or directive) may change expected behavior. Cite it next to the change. A bug fix that merely realigns code with the contract leaves contract text unchanged.
- Retirements keep the ID: set `Status: Retired (date)`, state the reason and citation, keep the original expectation as history. Never delete or reuse an ID.
- When the owner rules on intent ("intentional", "by design", "not a bug", directive, retirement) in an issue or PR comment, the same PR, or the next factory PR touching that area, must record it in docs/manual-qa as an `Owner ruling (date, issue comment link)` line on the relevant ID (or a new ID). Rulings in comments alone are not durable.
- Do not rewrite expected results to match what the code does. If code and contract disagree and no owner decision exists, it is a bug: file/reconcile it, leave the contract.
- Greptile flags user-facing PRs that touch behavior but not `docs/manual-qa/` (see `.greptile/config.json`, rule `manual-qa-contract-current`).
