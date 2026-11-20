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
