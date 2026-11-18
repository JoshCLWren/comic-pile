# History

**Route:** `/history`. All presentations must reflect persisted activity, not hypothetical events.

## MQA-HISTORY-001: Roll and rating history

**Test:** Roll and rate a QA issue; inspect History and thread detail.

**Expected:** Correct series, issue, die, rating and event ordering persist and agree.

## MQA-HISTORY-002: Snoozes are not reads

**Test:** Snooze or dismiss a pending QA roll and inspect corresponding events.

**Expected:** Actions are accurately classified; no invented rating/read or duplicated event.

## MQA-HISTORY-003: Cards/timeline/pagination agree

**Test:** Inspect the same events through all available history views and navigation.

**Expected:** Identity, timestamp, action and rating agree, without dropped or duplicate records.

## MQA-HISTORY-004: Sessionless history is one truthful chronological activity list

**Setup:** QA account with rolls, rerolls (snoozes), ratings, a manual die choice and a Reset Dice.

**Test:** Inspect History and compare die transitions and ratings with the Roll page.

**Expected:** History is a single chronological, owner-scoped list (no session summaries). Snoozes and ratings appear, a coalesced rate action shows the actual rating and the real before/after die with no impossible dice jumps. Source: [#4405](https://github.com/JoshCLWren/comic-pile/issues/4405); fixes #5349 and #5370 (issue #4822).
