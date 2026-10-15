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

**Expected:** Queue length alone does not change the chosen die. Fewer eligible candidates than faces means a smaller candidate pool.

## MQA-ROLL-006: Out-of-pool label matches visible rows

**Test:** Inspect the out-of-pool count and displayed rows, accounting for any filters or paging.

**Expected:** The count describes exactly the corresponding rows; no off-by-one or mismatched count.

## MQA-ROLL-007: Pending roll is preserved until resolved

**Test:** Roll once, request another before rating/snoozing/canceling, then resolve the first and roll again.

**Expected:** An unresolved selection cannot be silently overwritten. Normal rolling resumes after an explicit resolution and activity history is preserved.
