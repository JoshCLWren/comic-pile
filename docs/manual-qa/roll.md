# Roll

**Route:** `/` is the primary Roll page. `/roll` intentionally redirects to `/`. A die bounds the first eligible candidates in queue order; within that pool, contextual momentum, reading effort, and intent may weight selection.

## MQA-ROLL-001: Rating steps the die ladder

**Setup:** QA account with multiple active tracked series and a pending roll.

**Test:** Rate below 4.0, then rate at least 4.0 on a subsequent roll; also try the boundaries.

**Expected:** Below 4.0 steps UP; 4.0 or higher steps DOWN along d4, d6, d8, d10, d12, d20, d30, d50, d100, without wrapping. The correct issue and rating persist.

## MQA-ROLL-002: Never immediately repeat a low-rated series

**Setup:** QA series has at least one next unread issue; test plentiful, scarce, and zero alternative series.

**Test:** Roll a series, rate the comic below 4.0, then immediately request the next roll.

**Expected:** The same series must not be the very next selection, even if fewer alternatives than die faces exist. When no other series is eligible, explain that no alternative can be rolled instead of repeating it. Do not silently shrink/change the selected die to evade this rule. It is a next-roll exclusion, not a permanent ban.

## MQA-ROLL-003: Die faces reflect eligible queue order

**Setup:** More eligible QA series than die faces, plus blocked or snoozed rows.

**Test:** Inspect bounded candidates; move an outside eligible series to the front; inspect again.

**Expected:** Only the first eligible queued series occupy die faces. Blocked, snoozed, or excluded series cannot enter the pool. Moving a series changes position/membership but does not hard-code pick odds.

## MQA-ROLL-004: Contextual weighting and random bypass

**Setup:** Multiple eligible series and readable roll controls/selection context.

**Test:** Roll with differing reading intents or bandwidth, then select the explicit random intent. Inspect recorded selection weights/context where available.

**Expected:** Contextual momentum and reading effort may change candidate probabilities; explicit random bypass uses an unweighted choice. Every mode respects die eligibility. A small handful of rolls never proves uniformity or a top-position bias.

## MQA-ROLL-005: Die does not auto-size from queue length

**Test:** Choose a die manually, change number of eligible QA threads without rating, and reopen Roll.

**Expected:** Queue length alone does not change the chosen die. Fewer eligible candidates than faces means a smaller candidate pool. A manually selected die (for example d20) is recorded as the die actually used in the roll and session history, not the next ladder value (d30). Switching back to AUTO clears the manual override and resumes the automatic die policy rather than sticking to the manual or misrecorded value.

## MQA-ROLL-006: Out-of-pool label matches visible rows

**Test:** Inspect the out-of-pool count and displayed rows, accounting for any filters or paging.

**Expected:** The count describes exactly the corresponding rows; no off-by-one or mismatched count.

## MQA-ROLL-007: Pending roll is preserved until resolved

**Test:** Roll once, request another before rating/snoozing/canceling, then resolve the first and roll again.

**Expected:** An unresolved selection cannot be silently overwritten. Normal rolling resumes after an explicit resolution and activity history is preserved.

## MQA-ROLL-008: Navigation and cancellation preserve honest pending state

**Setup:** QA account with an eligible issue and a pending Roll selection.

**Test:** Leave Roll for Queue or a creator/thread page, use browser Back and Forward, and reload; then explicitly Cancel Roll. Repeat with a controlled cancel failure.

**Expected:** Navigation alone never silently drops or rerolls the unresolved selection. On return, the same canonical issue remains pending until the reader explicitly rates, snoozes, or cancels it according to session policy. Cancel Roll clears the pending selection and returns to the die-selection view only on success; failure leaves a usable retry path and truthful pending state. Actions do not fabricate reads, ratings, or cancellations in History. Navigation labels distinguish the die view from the Queue destination.

## MQA-ROLL-009: Manual selection searches without changing the die

**Setup:** QA library with many series, including two distinct Threads titled Superman.

**Test:** Open Pick manually, type a partial title and identifying year/volume when available; exercise keyboard navigation, no matches, clear, and selection of either same-named Thread.

**Expected:** Results filter responsively with accessible focus and controls; each choice identifies the correct existing Thread, not just its displayed title. Typing or clearing never rolls, rates, marks read, or changes the die. A confirmed manual choice records the exact canonical issue identity and is labeled Picked manually, never a fabricated result such as Rolled 0 of d6.

## MQA-ROLL-010: Covers, high zoom, and action accessibility

**Test:** View an unmapped QA series without cover art; inspect Roll at about 1280 px, 375 px, and 250-300% browser zoom. With keyboard and accessibility inspection, use die buttons (d4-d100/AUTO) and Reading Mode Intent/Bandwidth controls through idle, saving, success, and failure.

**Expected:** Missing art uses a purposeful accessible placeholder, not another title's cover. Navigation compacts before consuming the main reading surface; content and controls remain reachable at high zoom. Interactive controls expose correct names, roles and pressed/checked state, with enabled state when usable and disabled/busy only for real pending operations. Keyboard focus and recoverable error feedback remain usable.

## MQA-ROLL-011: Restored history is specific and truthful

**Setup:** QA account with a read/rated issue that can be restored and an event lacking a rating.

**Test:** Restore eligible history and inspect the RESTORED card, related session and Issue/Thread details.

**Expected:** A restored event names the actual series, canonical issue/number, and rating, or explicitly indicates no rating if none existed. Restoration does not invent a value, another issue, or a duplicate read/rate event; displays agree with persisted history.

## MQA-ROLL-012: Distinct identities and bounded stale suggestions

**Setup:** Two QA Threads with the same title but different canonical identities, plus more than one eligible stale series.

**Test:** Inspect Series Out of the Roll Pool and refresh the stale-series suggestion.

**Expected:** Same-name Threads remain separate with truthful identifying metadata (year, volume, publisher where known) or a safe Thread-specific fallback. No title-based merge or deletion occurs. The stale-series headline may count all eligible stale Threads while showing one featured suggestion; changing which one is featured does not imply missing data. Do not require a full unbounded stale-series list.

## MQA-ROLL-013: Blocker explanations and result copy stay accurate

**Setup:** QA issue with duplicate descriptions of one canonical prerequisite, and another with two genuinely distinct blocking edges.

**Test:** Inspect Reading Boundaries and story-arc counts, including zero and singular cases; use Roll result navigation.

**Expected:** One canonical prerequisite is described once; distinct prerequisites remain separately visible. Story-arc copy has proper spacing and singular/plural grammar. Back to Roll, View Queue and Cancel Roll each describe and perform their actual action without silently discarding a pending choice.

**Tracking:** Owner-approved Roll behavior [#3559](https://github.com/JoshCLWren/comic-pile/issues/3559); QA regressions [#3761](https://github.com/JoshCLWren/comic-pile/issues/3761) and [#3893](https://github.com/JoshCLWren/comic-pile/issues/3893). Historical closed QA issues are evidence, not proof of a passing current implementation.
