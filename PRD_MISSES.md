# PRD Misses Analysis

This document identifies gaps between the PRD (prd.md) requirements and the current implementation.

## Executive Summary

**Overall Status**: Approximately 90% of PRD features are implemented. Most core functionality is complete, with remaining gaps focused on:
- Configuration/settings management
- UI enhancements
- API response completeness
- Export formatting

## Detailed Analysis by PRD Section

### Section 1: Core Philosophy ✅ COMPLETE
- Chaos is allowed: **Implemented** (queue allows chaos, no strict ordering)
- Ratings and movement encode intent, not notes: **Implemented** (no notes system)
- Dice are sacred: **Implemented** (dice ladder logic enforced)
- Time, not mood, defines sessions: **Implemented** (6-hour session gap)
- Queue reflects what you can read now: **Implemented** (completed threads hidden)

### Section 2: Core Concepts ✅ COMPLETE
- Reading threads as atomic units: **Implemented**
- Single ordered queue: **Implemented**
- Rolls operate on top N rows: **Implemented**
- Completed threads disappear: **Implemented**
- Reactivation of completed threads: **Implemented** (via API)
- New threads insert at position 1: **Implemented**

### Section 2.3: Dice Ladder ✅ COMPLETE
- Allowed dice (d4, d6, d8, d10, d12, d20): **Implemented**
- New session starts at d6: **Implemented**
- Rating ≥ 4.0 → step down: **Implemented**
- Rating < 4.0 → step up: **Implemented**
- One step per read: **Implemented**
- Bounds enforcement: **Implemented**
- Manual overrides respect ladder: **Implemented**

### Section 3: Session Model ✅ COMPLETE
- 6-hour session boundary: **Implemented**
- No manual "start new session" button: **Implemented**
- Pending reads tracking: **Implemented**
- Roll-and-skip logging: **Implemented**

### Section 4: Roll Behavior ✅ COMPLETE
- Roll pool definition (first N active threads): **Implemented**
- Manual override support: **Implemented**

### Section 5: Rating Model ✅ MOSTLY COMPLETE
- Rating scale (0.5 → 5.0): **Implemented**
- Progress rules (rating decrements issues): **Implemented**
- Queue movement based on rating: **Implemented**
- **MISSING**: Issues read adjustment UI (covered by TASK-108)

### Section 6: Completion Semantics ✅ COMPLETE
- Thread completion on issues_remaining = 0: **Implemented**
- Completion removes from roll pool: **Implemented**
- Reactivation when new issues owned: **Implemented**

### Section 7: Staleness Awareness ✅ PARTIAL
- Last read/rating/review timestamps: **Implemented** (in model)
- Stale thread tracking: **Implemented** (get_stale_threads API)
- **MISSING**: Staleness awareness UI on roll screen (TASK-102)

### Section 8: Time Tracking ✅ COMPLETE
- Raw timestamps for all events: **Implemented**
- No derived labels: **Correctly avoided**

### Section 9: Reviews & External Data ✅ MOSTLY COMPLETE
- Review URL storage: **Implemented** (review_url field in Thread model)
- Review timestamp storage: **Implemented** (last_review_at field in Thread model)
- **MISSING**: Review URL in API response (TASK-201)
- **MISSING**: Review timestamp import API (TASK-111)

### Section 10: Export Policy ✅ PARTIAL
- Raw data export (JSON): **Implemented** (/admin/export/json/)
- Raw data export (CSV): **Implemented** (/admin/export/csv/)
- **MISSING**: Narrative summary export (TASK-112)

### Section 11: Narrative Session Summary ✅ MOSTLY COMPLETE
- Narrative summaries for sessions: **Implemented** (build_narrative_summary in session.py)
- Read/Skipped/Completed categorization: **Implemented**
- Session details view: **Implemented** (/sessions/{id}/details)
- **MISSING**: Human-readable narrative export format (TASK-112)

### Section 12: Data Model (JSON v1) ✅ MOSTLY COMPLETE
- Settings object in data model: **NOT IMPLEMENTED** (settings are hardcoded)
- All thread fields: **MOSTLY COMPLETE**
- Session data: **Implemented**
- Events data: **Implemented**

### Section 13: Wireframes ✅ PARTIAL
- Roll screen: **Implemented**
- Rate screen: **Implemented**
- Queue screen: **Implemented**
- **MISSING**: Roll pool highlighting (TASK-103)
- **MISSING**: Star ratings display (TASK-105)
- **MISSING**: Completed threads toggle (TASK-104)

## Missing Features Summary

### High Priority
None - all core functionality is implemented

### Medium Priority
1. **Configurable Session Settings** (TASK-200)
   - PRD Section 12 shows settings object
   - Currently: session_gap_hours, start_die, rating_scale are hardcoded
   - Needed: Settings model and API endpoints

2. **Narrative Session Summaries** (TASK-101)
   - PRD Section 11 requires narrative summaries
   - Partially implemented in session details
   - Needed: Full narrative summary feature

3. **Staleness Awareness UI** (TASK-102)
   - PRD Section 7 requires stale thread suggestions
   - Backend API exists (/threads/stale)
   - Needed: UI display on roll screen

### Low Priority
1. **Review URL in Thread API Response** (TASK-201)
   - review_url field exists in model
   - Missing from ThreadResponse schema
   - Needed: Include in API responses

2. **Issues Read Adjustment UI** (TASK-108)
   - Currently hardcoded to 1
   - PRD Section 13 shows increment/decrement controls
   - Needed: UI controls for issues_read field

3. **Queue UI Enhancements** (TASK-103, TASK-104, TASK-105)
   - Roll pool highlighting
   - Completed threads toggle
   - Star ratings display

4. **Review Timestamp Import** (TASK-111)
   - last_review_at field exists in model
   - Needed: API to import from League of Comic Geeks

5. **Narrative Summary Export** (TASK-112)
   - Raw JSON export exists
   - Needed: Human-readable export format

## Complete Task List for PRD Alignment

### Already Defined Tasks (TASK-101 through TASK-123)
These tasks cover most identified gaps and are already in the system.

### New Tasks Created
- **TASK-200**: Configurable Session Settings (MEDIUM, 4 hours)
- **TASK-201**: Include review_url and last_review_at in Thread API Response (LOW, 30 minutes)

## Conclusion

The implementation is **very close to PRD compliance**. Core features are complete and working. Remaining gaps are primarily:
1. Configuration (making hardcoded values configurable)
2. UI polish (existing APIs need UI)
3. API completeness (some model fields not exposed)
4. Export formatting (human-readable vs raw data)

All gaps have been tracked as tasks in the system for prioritization and completion.
