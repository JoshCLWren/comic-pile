# Creators

**Routes:** `/creators`, `/creators/:creatorKey`, `/creators/compare`.

## MQA-CREATOR-001: Creator counts reconcile

**Setup:** Known credited/read/rated QA comics.

**Test:** Inspect creator aggregate counts and open contributing comics.

**Expected:** Denominators are consistent; impossible fractions do not appear; underlying issues support the totals.

## MQA-CREATOR-002: Metrics drill into source records

**Test:** Navigate from creator counts/credits to underlying comics and back.

**Expected:** Links identify the correct creator/issue; detail agrees with summary, without hard-coded phantom data.

## MQA-CREATOR-003: Comparison uses equal definitions

**Setup:** Two creators with some shared and distinct credits.

**Test:** Open comparison and inspect each side.

**Expected:** Metrics use equivalent definitions, creator identities are correct, and shared credits are not double-counted within one creator.
