# Fix for Issue #4283: Reading Plans list page returns 409 after list deletion

## Problem

When a user adopts a CBL source (creating a plan and a linked Reading List), then deletes that list, the Reading Plans list page (`/continuity-plans`) returns HTTP 409 with no entries. Individual plan detail pages continue to work correctly.

### Root Cause

The `list_continuity_plan_items` function in `app/services/continuity_plan_writer.py` enforces that every plan must have an authoritative Reading List when Option E is enabled. After a linked list is deleted, the plan becomes orphaned (no ReadingPlanSource row), causing the function to raise a 409 error:

```python
if len(authorities) != len(ordered):
    raise HTTPException(
        status_code=409,
        detail="Reading Plan has no linked authoritative Reading List",
    )
```

This is overly strict because:
1. Orphaned plans remain owned by the user and should be visible
2. Individual plan detail pages work fine (they don't require the list authority)
3. The error message is misleading - the plan itself exists and is owned

## Solution

Modified `list_continuity_plan_items` to allow orphaned plans in the list index. The function now only rejects plans when there are ambiguous or foreign list authorities, not when a plan has no linked list at all.

### Changes Made

#### 1. `app/services/continuity_plan_writer.py` (lines 927-944)

**Before:**
```python
if get_reading_execution_settings().enabled and ordered:
    list_rows = await owned_plan_list_authority_rows(...)
    authorities: dict[int, tuple[int, str, datetime]] = {}
    for plan_id, list_id, mode, list_updated_at in list_rows:
        existing = authorities.get(plan_id)
        if existing is not None and existing[0] != list_id:
            raise HTTPException(status_code=409, detail="Ambiguous Reading List association")
        authorities[plan_id] = (list_id, mode, list_updated_at)
    if len(authorities) != len(ordered):
        raise HTTPException(
            status_code=409,
            detail="Reading Plan has no linked authoritative Reading List",
        )
```

**After:**
```python
if get_reading_execution_settings().enabled and ordered:
    list_rows = await owned_plan_list_authority_rows(...)
    authorities: dict[int, tuple[int, str, datetime]] = {}
    for plan_id, list_id, mode, list_updated_at in list_rows:
        existing = authorities.get(plan_id)
        if existing is not None and existing[0] != list_id:
            raise HTTPException(status_code=409, detail="Ambiguous Reading List association")
        authorities[plan_id] = (list_id, mode, list_updated_at)
    # Allow orphaned plans (linked lists deleted) to be listed without authority.
    # Individual plan detail pages still work, and orphaned plans remain owned.
    # Only reject when there are ambiguous or foreign list authorities.
```

#### 2. `tests/test_option_e_plan_index.py`

Updated the test `test_option_e_index_rejects_unlinked_plan_instead_of_showing_stale_order` to verify that orphaned plans are now allowed in the list index.

Added new test `test_option_e_index_rejects_multiple_authoritative_lists_for_same_plan` to ensure that ambiguous list authorities are still rejected (maintaining the original safeguard).

### Behavior Changes

**Before the fix:**
- Reading Plans list page returns 409 when any plan has no linked authoritative Reading List
- All plans disappear from the index, even if they are owned and valid

**After the fix:**
- Orphaned plans (linked lists deleted) appear in the index without authority information
- Plans with ambiguous or foreign list authorities still return 409
- Individual plan detail pages continue to work as before

### Orphaned Plan Display

Orphaned plans in the index will have:
- `source_paths: []` (empty, since there's no authoritative list)
- `step_count: 0` (or the count from `nodes_json` in legacy mode)
- The plan's original `ordering_mode`, `lane_count`, and `name`

This allows users to see orphaned plans and potentially re-link them to a new list if desired.

## Testing

### Unit Tests

Updated and added tests in `tests/test_option_e_plan_index.py`:
- `test_option_e_index_allows_orphaned_plan_after_list_deletion`: Verifies orphaned plans are listed
- `test_option_e_index_rejects_multiple_authoritative_lists_for_same_plan`: Verifies ambiguity is still rejected

### Manual Verification Steps

1. Adopt a CBL source (e.g., "B.P.R.D. Plague of Frogs Omnibus Vol. 3")
   - This creates a plan and a linked Reading List
   - Navigate to `/continuity-plans` - the plan should appear

2. Delete the newly adopted list
   - Navigate to `/continuity-plans` again
   - The plan should still appear (orphaned, without list authority)

3. Navigate to the plan detail page directly (e.g., `/continuity-plans/10000028`)
   - The page should load correctly

4. Create a plan with two different authoritative lists linked
   - This should still return 409 (ambiguous authority)

5. Create a plan linked to a foreign user's list
   - This should still return 409 (foreign authority)

## Backward Compatibility

This change is backward compatible:
- Plans with authoritative lists continue to work as before
- Plans without lists (orphaned) now appear instead of returning 409
- Ambiguous and foreign list authorities are still rejected
- No API contract changes - the same `ContinuityPlanListItem[]` response is returned

## Related Issues

- Issue #4283: Reading Plans list page returns 409 with no entries after an adopted list is deleted
- Issue #4255: MQA-CBL-005 / Reading Lists follow-up (parent issue for acceptance)
- Option E contract: `docs/READING_PLAN_CANONICAL_MODEL.md`

## Migration Notes

No database migration required. The change is purely in the list retrieval logic.

## Future Work

Consider adding UI feedback for orphaned plans (e.g., a note indicating the plan has no linked list). This could be done in a follow-up issue.
