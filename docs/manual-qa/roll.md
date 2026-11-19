# Roll

**Route:** `/` is the primary Roll page. `/roll` intentionally redirects to `/`. A die bounds the first eligible candidates in queue order; selection within that pool is uniform. **Amended 2026-11-18:** Roll is sessionless and event-derived per the owner's approved contract in [#4405](https://github.com/JoshCLWren/comic-pile/issues/4405) (2026-10-30/31); weighting by reading mode, bandwidth or intent was removed from the product by that decision.

## MQA-ROLL-001: Rating steps the die ladder

**Owner ruling (#4354, 2026-11-03; #4405):** the Auto/Manual session-mode UI and `session-mode` mutation were removed with no replacement; the rating threshold is 4.0.

**Setup:** QA account with multiple active tracked series and a pending roll.

**Test:** Rate below 4.0, then rate at least 4.0 on a subsequent roll; also try the boundaries.

**Expected:** Below 4.0 steps UP; 4.0 or higher steps DOWN along d2, d4, d6, d8, d10, d12, d20, staying on the boundary at either end (no wrapping). The default and Reset value is d6. The correct issue and rating persist.

**Amended 2026-11-18 (UPDATE):** ladder changed from d4..d100 to d2..d20 by owner decision [#4405](https://github.com/JoshCLWren/comic-pile/issues/4405); there is no d30, d50 or d100.

## MQA-ROLL-002: Never immediately repeat a low-rated series

**Setup:** QA series has at least one next unread issue; test plentiful, scarce, and zero alternative series.

**Test:** Roll a series, rate the comic below 4.0, then immediately request the next roll.

**Expected:** The same series must not be the very next selection, even if fewer alternatives than die faces exist. When no other series is eligible, explain that no alternative can be rolled instead of repeating it. Do not silently shrink/change the selected die to evade this rule. It is a next-roll exclusion, not a permanent ban.

## MQA-ROLL-003: Die faces reflect eligible queue order

**Setup:** More eligible QA series than die faces, plus blocked or snoozed rows.

**Test:** Inspect bounded candidates; move an outside eligible series to the front; inspect again.

**Expected:** Only the first eligible queued series occupy die faces. Blocked, snoozed, or excluded series cannot enter the pool. Moving a series changes position/membership but does not hard-code pick odds.

## MQA-ROLL-004: Contextual weighting and random bypass

**Status: Retired (2026-11-18)** -- owner decision [#4405](https://github.com/JoshCLWren/comic-pile/issues/4405): "no reading-mode quiz, bandwidth/intent predictor, or recommendation weighting"; every candidate in the pool has equal odds. Replaced by MQA-ROLL-016. The Reading Mode quiz launcher is also feature-flagged off (`frontend/src/config/features.ts`, #1945).

**Original expectation (historical):** Contextual momentum and reading effort could change candidate probabilities; an explicit random intent was unweighted.

## MQA-ROLL-005: Die does not auto-size from queue length

**Test:** Choose a die manually, change number of eligible QA threads without rating, and reopen Roll.

**Expected:** Queue length alone does not change the chosen die. Fewer eligible candidates than faces means a smaller candidate pool. A manually selected die (for example d12) is recorded as the die actually used in the roll and activity history, not the next ladder value (d20). Per [#4405](https://github.com/JoshCLWren/comic-pile/issues/4405) (UPDATE 2026-11-18), manual selection sets the die once and does not pin it: subsequent ratings and rerolls move the die normally along the ladder, and Reset Dice returns it to d6.

## MQA-ROLL-006: Out-of-pool label matches visible rows

**Status: Retired (2026-11-18)** -- the out-of-pool/blocked/stale diagnostic sections were deleted from Roll (owner-approved in #4405; implemented by #4441 / PR #4474, merged Nov 1). Roll shows only the bounded pool.

**Original expectation (historical):** The count describes exactly the corresponding rows; no off-by-one or mismatched count.

## MQA-ROLL-007: Roll again replaces the pending selection

**Owner ruling ([#4338](https://github.com/JoshCLWren/comic-pile/issues/4338), [#4339](https://github.com/JoshCLWren/comic-pile/issues/4339), [#4405](https://github.com/JoshCLWren/comic-pile/issues/4405)):** snooze acts as a reroll. The separate Snooze/Skip endpoints and buttons were retired; pressing Roll again on a pending comic is the snooze, per the approved sessionless Roll contract.

**Test:** Roll once, request another before rating/snoozing/canceling.

**Owner ruling (2026-11-16, [#5262 comment](https://github.com/JoshCLWren/comic-pile/issues/5262#issuecomment-6922279397), [#4472 comment](https://github.com/JoshCLWren/comic-pile/issues/4472#issuecomment-6922434724), docs PR #5295):** "Roll again" is an explicit new-roll request; replacing the pending selection is intended and is not a bug. Do not re-file.

**Expected:** Requesting another roll is an explicit choice that discards the pending selection and rolls a new one (owner ruling #5267, 2026-11-16). Per [#4405](https://github.com/JoshCLWren/comic-pile/issues/4405) the reroll records a snooze event for the passed comic, excludes it temporarily in this browser, moves the logical die one step up (maximum d20) and immediately selects again; there is no separate Snooze or Skip button. Both roll events are preserved in activity history. Navigation, reload, and Back to Queue preserve the pending selection; only an explicit new roll, snooze, cancel, or rate replaces it.

## MQA-ROLL-008: Navigation and cancellation preserve honest pending state

**Setup:** QA account with an eligible issue and a pending Roll selection.

**Test:** Leave Roll for Queue or a creator/thread page, use browser Back and Forward, and reload; then explicitly Cancel Roll. Repeat with a controlled cancel failure.

**Expected:** Navigation alone never silently drops or rerolls the unresolved selection. On return, the same canonical issue remains pending until the reader explicitly rates, snoozes, or cancels it until Reset Dice. Cancel Roll clears the pending selection and returns to the die-selection view only on success; failure leaves a usable retry path and truthful pending state. Actions do not fabricate reads, ratings, or cancellations in History. Navigation labels distinguish the die view from the Queue destination.

## MQA-ROLL-009: Manual selection searches without changing the die

**Setup:** QA library with many series, including two distinct Threads titled Superman.

**Test:** Open Pick manually, type a partial title and identifying year/volume when available; exercise keyboard navigation, no matches, clear, and selection of either same-named Thread.

**Expected:** Results filter responsively with accessible focus and controls; each choice identifies the correct existing Thread, not just its displayed title. Typing or clearing never rolls, rates, marks read, or changes the die. A confirmed manual choice records the exact canonical issue identity and is labeled Picked manually, never a fabricated result such as Rolled 0 of d6.

## MQA-ROLL-010: Covers, high zoom, and action accessibility

**Test:** View an unmapped QA series without cover art; inspect Roll at about 1280 px, 375 px, and 250-300% browser zoom. With keyboard and accessibility inspection, use the die buttons (d2-d20) through idle, saving, success, and failure.

**Expected:** Missing art uses a purposeful accessible placeholder, not another title's cover. Navigation compacts before consuming the main reading surface; content and controls remain reachable at high zoom. Reading Mode Intent/Bandwidth controls are no longer part of Roll (#4405; UPDATE 2026-11-18). Interactive controls expose correct names, roles and pressed/checked state, with enabled state when usable and disabled/busy only for real pending operations. Keyboard focus and recoverable error feedback remain usable.

## MQA-ROLL-011: Restored history is specific and truthful

**Setup:** QA account with a read/rated issue that can be restored and an event lacking a rating.

**Test:** Restore eligible history and inspect the RESTORED card, related session and Issue/Thread details.

**Expected:** A restored event names the actual series, canonical issue/number, and rating, or explicitly indicates no rating if none existed. Restoration does not invent a value, another issue, or a duplicate read/rate event; displays agree with persisted history.

## MQA-ROLL-012: Distinct identities and bounded stale suggestions

**Status: Retired (2026-11-18)** -- the stale-series suggestion and Out-of-the-Roll-Pool sections were removed with #4441 / PR #4474. Same-name Threads must still stay separate (see MQA-ROLL-009). Prior intent ruling kept for history: owner confirmed on #3457 (2026-10-14) that one random stale suggestion among N was intentional, not a missing-rows bug.

**Original expectation (historical):** Same-name Threads remain separate with truthful identifying metadata (year, volume, publisher where known) or a safe Thread-specific fallback. No title-based merge or deletion occurs. The stale-series headline may count all eligible stale Threads while showing one featured suggestion; changing which one is featured does not imply missing data. Do not require a full unbounded stale-series list.

## MQA-ROLL-013: Blocker explanations and result copy stay accurate

**Setup:** QA issue with duplicate descriptions of one canonical prerequisite, and another with two genuinely distinct blocking edges.

**Test:** Inspect Reading Boundaries and story-arc counts, including zero and singular cases; use Roll result navigation.

**Expected:** One canonical prerequisite is described once; distinct prerequisites remain separately visible. Story-arc copy has proper spacing and singular/plural grammar. Back to Roll, View Queue and Cancel Roll each describe and perform their actual action without silently discarding a pending choice.

**Tracking:** Owner-approved Roll behavior [#3559](https://github.com/JoshCLWren/comic-pile/issues/3559); QA regressions [#3761](https://github.com/JoshCLWren/comic-pile/issues/3761) and [#3893](https://github.com/JoshCLWren/comic-pile/issues/3893). Historical closed QA issues are evidence, not proof of a passing current implementation.

## MQA-ROLL-014: Reroll snoozes are temporary and never backfill the die

*(ID note: this scenario previously duplicated the heading MQA-ROLL-010; it is renumbered MQA-ROLL-014 on 2026-11-18. MQA-ROLL-010 refers to the covers/zoom/accessibility scenario only.)*

**Setup:** More than twenty eligible QA series; use d20.

**Test:** Choose Roll again repeatedly, inspect the pool, then reload. Continue until no alternative remains. Choose Reset Dice and confirm.

**Expected (UPDATE 2026-11-18, owner decision [#4405](https://github.com/JoshCLWren/comic-pile/issues/4405), "Do not backfill snoozed candidates"):** The pool is the top N ranked readable series before this browser's temporary snoozes are applied. A series ranked beyond N never enters merely because one of the first N was snoozed. As the pool is snoozed away the effective die may shrink to match the available choices without overwriting the logical die. Temporary snoozes persist through reload in the same browser until local midnight (or Reset Dice) and each reroll also records a durable snooze event. Exhaustion shows Add Comics or Reset Dice when resetting would restore candidates; it never auto-restores snoozed comics. Reset Dice records a reset event, sets d6, clears browser snoozes and the pending offer, and does not erase reading progress, ratings or history. Browser hints never override owner-scoped reading constraints.

**Original wording superseded:** "Snoozed series leave the pool before the die limit is applied; later eligible series fill the open faces."

**Unsnooze (UPDATE 2026-11-18, [#4589](https://github.com/JoshCLWren/comic-pile/issues/4589)):** Roll again persists each snooze on the session. Unsnooze (Roll shelf or Queue) removes the chosen snooze and clears its browser cookie id. When it is the most recent snooze and no later action (manual pick, die choice, rating, undo, reset) happened since, it also restores that series as the pending roll and returns the die to its pre-snooze size; otherwise only the snooze is removed and the current pending roll and die are left alone. Unsnoozing an already-removed snooze succeeds without changes (safe retry after a lost response). Reset Dice clears the saved snoozes. Unsnooze failures show a visible error. MQA-ROLL-007, MQA-ROLL-008 and the Queue snooze scenario MQA-QUEUE-003: contract unchanged apart from the unsnooze behavior described here.

## MQA-ROLL-015: Undo rating restores the die step

**Setup:** QA account with a pending Roll offer on d12 or similar.

**Test:** Rate below 4.0 (die steps up), then use the immediate Undo rating on the Roll page; reload and roll again. Repeat for a rating of 4.0 or higher.

**Expected:** Undo reverts the rating and read state and restores the die to its pre-rating step, and the pending offer is restored; the next roll uses the restored die. Per [#4405](https://github.com/JoshCLWren/comic-pile/issues/4405), a correction of the latest rating undoes its own die and queue effects only when no later dice-changing action superseded it. Historical rating edits never mark issues unread. Source: regression report [#5380](https://github.com/JoshCLWren/comic-pile/issues/5380).

## MQA-ROLL-016: Uniform selection and few-choice states

**Setup:** QA pools with many, three, two, one and zero eligible candidates.

**Test:** Roll with each pool size (including three candidates on a d4).

**Expected:** All candidates in the pool have equal odds. Two candidates behave as a d2 coin flip; one candidate skips rolling and shows Read Now; zero shows Add Comics or Reset Dice when resetting snoozes would restore candidates. No fictitious die faces for nonmatching sizes. Source: #4405 (2026-10-31). Replaces retired MQA-ROLL-004.

## MQA-ROLL-017: Direct Mark Read does not move the die or queue

**Setup:** QA series with an unread issue, outside any Roll offer.

**Test:** Use Mark Read from a Thread/Issue card; the rating slider defaults to 3.5; save with several ratings including below 4.0. Repeat on a blocked issue.

**Expected:** A rating is always recorded (default 3.5 or edited), durable read progress is saved, and neither the die nor the queue position changes regardless of the chosen rating. Direct reading and rating of an owned issue is never vetoed by eligibility, queue rank, holds or prerequisites (manual read allowed even when blocked, #4708). A Roll-flow rating (threshold 4.0) does move the die and then rolls the next comic. Source: #4405.
