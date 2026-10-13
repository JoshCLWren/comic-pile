# ComicPile Roll Eligibility Contract (Josh, 2026-10-12, authoritative)

A reading list says what order Josh intends to read. A checkpoint tells Roll what it may not offer yet. They are different things.

## Core rule
Roll may offer a Thread's next unread issue only when the Thread is active and eligible for the current session, and every explicitly required prerequisite issue has been read.
- Custom CBLs own the intended reading order, and Reading Plans read that order from them.
- Canonical issue-to-issue Dependencies own the hard Roll restrictions.
- "Strict" means enforcing the checkpoints Josh selected. It does not mean every adjacent CBL entry blocks the next one. A plan can hold 500 comics and zero hard checkpoints.

## What may create a hard prerequisite
A hard prerequisite must be all three:
- **Specific:** it names real source and target Issue IDs.
- **Authoritative:** it comes from a checkpoint Josh selected, a prerequisite he recorded, or a reading-order requirement he verified and accepted.
- **Necessary:** removing it would let Roll offer a comic before something Josh actually requires reading first.

Allowed:
- An explicit checkpoint between two issues.
- An existing crossover prerequisite Josh authored, once verified.
- A convergence point that needs several source issues read first.
- An issue-specific annual, special or crossover placement backed by an accepted requirement.

Not allowed:
- Treating consecutive CBL entries as a blocker by default.
- Blocking just because the list changes series.
- Adding blockers for same-series order, which `Issue.position` and `next_unread_issue_id` already handle.
- Gating every annual or special automatically.
- Turning a whole strict plan into one chain.
- Keeping a requirement only because an old generated rule exists.

## Checkpoint representation
Each checkpoint resolves to a durable source Issue ID, a target Issue ID and its provenance. An issue can have several prerequisites.

The current `is_checkpoint` flag targets the next node in the same lane. Verify that this is really the intended target, and don't swap one accidental adjacency for another. Editing or reordering a list must never silently redirect an existing checkpoint to a different comic. If checkpoints need explicit targets, extend the existing CBL checkpoint metadata narrowly. Don't build a new ordering engine.

## Annuals, specials and Giant-Size
- These keep their own publishing Threads, and the custom CBL places them in the reading order.
- Create hard prerequisites for them only where a specific issue has an established requirement.
- Don't merge them into the parent series. Don't gate a whole run at its first issue, and don't let them stop the parent series unless a specific checkpoint says so.
- Once Annual #1 is read, Annual #2 becomes that thread's next unread issue. If Annual #2 belongs later in the main series, it needs its own checkpoint.

## Legacy cleanup (prod)
1. Classify every edge and rule by origin, source, target, owner, reason, and whether it affects today's Roll.
2. Keep Josh's real checkpoints and standalone prerequisites, including constraints shared between plans.
3. Retire only restrictions proven to be generated list order, and remove their rule records only if nothing else needs them.
4. Check the 365 rows called "natural-order". If they are `Issue.position` or normal series progression, keep them. If they are hard Dependency rows that just duplicate series order, they must not stay authoritative blockers.
5. Work through the 93 borderline rows in batches, recording each one's disposition with its evidence and a confidence level.
   - Keep proven hard requirements, and retire proven generated adjacency.
   - Investigate the unclear ones using CBL and source history and Josh's earlier decisions.
   - Escalate only real reader-intent questions that change current or near-future Roll eligibility.
6. Prove that creating, editing, importing, or saving an unchanged plan can't bring the retired chains back.

Prod data rules:
- Read-only preflight, then scoped, transactional changes with a rollback.
- No Neon clones, branches or snapshots.
- Josh approves the exact production mutations. Ordinary code PRs don't need his approval.

## Required tests
- Series A and B advance independently between selected checkpoints.
- An unread A→B checkpoint blocks B, and reading A makes B eligible.
- With several prerequisites, all of them must be read.
- Ordinary CBL adjacency never creates a hard blocker.
- Annual #2 stays blocked when it has its own documented later checkpoint.
- Saving an unchanged plan changes nothing: issue identity, membership, hard Dependencies and Roll eligibility all stay the same.
- Editing a CBL keeps existing checkpoint targets unless someone changes them on purpose.
- Overlapping plans share read state and prerequisites without dropping each other's requirements.
- The existing Starman/JSA gates still work.
  - The Wild Hunt #3 check from the source spec is dropped because Josh has finished Wild Hunt.
- Retired generated rules don't come back after saving or applying a plan.

## Production acceptance
- Produce a full before/after eligibility diff for user 1. List every thread that becomes newly eligible or newly blocked, with its next unread issue and the prerequisites that survived or were retired.
- 52→235 eligible is a prediction, not a target, so don't tune the implementation to reach it.
- Accept only when every surviving blocker has evidence behind it and every removed blocker is shown to be redundant or unwanted.
- Automatically check every eligible issue whose status changes. Then hand-inspect 15–20 of them, including several of the newly unlocked threads.
  - **Mignolaverse:** Abe Sapien and B.P.R.D. titles shouldn't hit early crossover gates.
  - **X-Men:** Magneto War, Hunt for Xavier, Cable and X-Force should be gated only by real crossover prerequisites.
  - **Starman/JSA:** Starman #55 still gates the start of the JSA project.
  - **Fantastic Four:** annuals and Giant-Size issues sit where they belong without being required at every transition.
  - **Kirby Fourth World:** Jimmy Olsen, New Gods and Mister Miracle can progress between real crossover points.
  - **Ultimate and Absolute:** the One Year In and Two Years In gates and other accepted event checkpoints survive, with no whole-line chains.
  - **JLI, Hickman FF and Starlin:** genuine hand-authored requirements survive, and ordinary list adjacency doesn't.
