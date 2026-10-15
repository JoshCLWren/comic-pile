# Analytics

**Expected route:** `/analytics` must be a dedicated Analytics page, not a redirect to Roll. The owner explicitly confirmed this future behavior; no specific chart set was mandated.

## MQA-ANALYTICS-001: Independent Analytics navigation

**Test:** When implemented, open `/analytics` directly and through the UI; reload.

**Expected:** A distinct Analytics page appears and navigation remains stable instead of redirecting to Roll.

## MQA-ANALYTICS-002: Metrics reconcile with real history

**Setup:** QA account with known comics, ratings and read events.

**Test:** Inspect displayed metrics and their backing history or drill-down.

**Expected:** Each metric has a clear definition and agrees with persisted source records; no impossible denominator or other-user data.

## MQA-ANALYTICS-003: Analytics updates after activity

**Test:** Rate/read a QA issue, refresh Analytics and compare History.

**Expected:** After refresh, analytics reflects the same activity without claiming stale data is fresh.
