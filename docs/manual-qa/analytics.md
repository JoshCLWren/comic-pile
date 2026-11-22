# Analytics

**Status: Retired (2026-11-18).** The dedicated Analytics page was deleted by owner decision on [#5437](https://github.com/JoshCLWren/comic-pile/issues/5437) (merged in [#5446](https://github.com/JoshCLWren/comic-pile/pull/5446)). IDs 001-003 below are kept, never reused, and are not acceptance targets; MQA-ANALYTICS-004 remains active. Creator analytics belongs to [Creators](creators.md).

## MQA-ANALYTICS-001: Independent Analytics navigation

**Status: Retired (2026-11-18)** -- owner decision on #5437 / #5446 superseded the earlier requirement for a distinct `/analytics` page.

**Original expectation (historical):** `/analytics` is a dedicated Analytics page, not a redirect to Roll.

## MQA-ANALYTICS-002: Metrics reconcile with real history

**Status: Retired (2026-11-18)** -- the page and its metrics were removed (#5446). Metric reconciliation for Creators is covered by MQA-CREATOR-001..003.

**Original expectation (historical):** Each metric has a clear definition and agrees with persisted source records; no impossible denominator or other-user data.

## MQA-ANALYTICS-003: Analytics updates after activity

**Status: Retired (2026-11-18)** -- the page was removed (#5446).

**Original expectation (historical):** After refresh, analytics reflects the same activity as History without claiming stale data is fresh.

## MQA-ANALYTICS-004: Old `/analytics` bookmarks still land on Roll

**Test:** Open `/analytics` directly and reload.

**Expected:** The app redirects to the Roll page (`/`) without an error or blank page. No Analytics navigation entry exists. Source: owner decision on #5437 ("the `/analytics` redirect stays for old bookmarks"), #5446.
