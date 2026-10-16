# Tags

Tags can be private or global. They can be assigned to supported threads, issues, and reading plans; effective issue tags include allowed inherited assignments.

## MQA-TAG-001: Create with one of 32 colors

**Test:** Create a QA tag from an item's tag editor, choose a nondefault color, and reload.

**Expected:** The palette offers 32 colors; the chosen color and tag assignment persist and the chip displays consistently.

## MQA-TAG-002: Duplicate tag reuse

**Setup:** A QA tag already exists.

**Test:** Try creating an exact normalized duplicate with different case or spacing, then choose the reuse action. Also try a merely similar global tag name.

**Expected:** Exact duplicates trigger a warning and are not created; the existing tag can be reused. Similar names receive sensible guidance and private/global permissions are respected.

## MQA-TAG-003: Edit and delete with usage awareness

**Test:** Rename or recolor a private QA tag, inspect affected chips, then delete it.

**Expected:** Edits propagate correctly; deletion describes affected usage and removes only intended assignments. Admin permissions apply to global tags.

## MQA-TAG-004: Bulk-assign without duplicates

**Setup:** Several selected QA threads.

**Test:** Bulk-apply a tag, repeat the same action, and inspect selected and unselected threads.

**Expected:** Every selected thread carries the tag exactly once; unrelated threads remain unchanged.

## MQA-TAG-005: Direct and inherited tags

**Setup:** An issue belongs to a tagged QA thread and tagged plan, optionally with the same tag assigned directly.

**Test:** Inspect effective tags and inheritance sources; remove one contributing source.

**Expected:** The issue inherits the union of visible thread/plan/direct tags. Duplicate effective chips display once with all contributing sources. Removing one source does not erase a still-inherited tag. Private tags never leak between users.

## MQA-TAG-006: Dedicated tag management page

**Test:** Once built, visit `/tags`, search the library's tags, create/edit/delete a permitted tag, then use an inline tag editor.

**Expected:** `/tags` is a real searchable tag-management page, not a redirect or 404. Inline tagging remains available. This owner-confirmed expectation remains in the inventory before implementation.

Tag-based Roll inclusion/exclusion was mentioned as an absence in the original ZIP but is **not** an approved requirement here. Do not infer it is owed.
