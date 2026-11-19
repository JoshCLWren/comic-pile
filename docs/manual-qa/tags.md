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

## MQA-TAG-007: Inherited sources are legible and navigable

**Setup:** An issue with direct, Thread-inherited and Reading List-inherited QA tags, including a typical 20-character name.

**Test:** Inspect Roll chips at about 1280 px and 375 px, then view the source picker and follow each source link from the Thread tag editor.

**Expected:** Typical tag names remain legible before decorative inheritance text, with full accessible names for actual truncation. Source labels say Reading plan: [name], Thread or issue as appropriate, never internal names such as ContinuityPlan; unknown types have safe human-readable fallback. A source pointing to the current Thread is not an inert self-link; external/other-Thread sources navigate meaningfully. Direct and inherited attribution remains accurate.

## MQA-TAG-008: Color choices work as a radio group

**Test:** Use only the keyboard to enter the 32-swatch tag palette, change colors with all four arrow keys across ends, then Tab and Shift+Tab out; inspect accessibility information.

**Expected:** One swatch is selected at a time with radio-group semantics, named colors, accurate checked state, wrapping arrow navigation and a predictable roving Tab stop. Existing focus visibility and Escape behavior remain functional.

## MQA-TAG-009: Changes report truthful, grammatical feedback

**Test:** Rename a QA tag, bulk-assign to one and many issues, remove a direct tag that is still inherited, and exercise zero/one/many usage counts.

**Expected:** Rename feedback displays the new name or clear old-to-new wording. Bulk-success messages use sentence case; issue/assignment counts use correct singular/plural forms. Removing only a direct assignment says the tag remains inherited rather than claiming the comic is untagged. Success is never shown for a failed mutation.

## MQA-TAG-010: Long names stay contained and accessible

**Test:** Apply tag names between 68 and 100 characters in dialogs, rows, chips, and Roll at desktop and narrow widths.

**Expected:** Names wrap or truncate within bounded layouts without stretching dialogs or obscuring actions. The complete tag value remains available to assistive technology and via an appropriate tooltip; typical short names are not unnecessarily clipped.

**Tracking:** Approved Tags work [#3557](https://github.com/JoshCLWren/comic-pile/issues/3557). These expected behaviors do not imply tag-based Roll filtering was approved.

Tag-based Roll inclusion/exclusion was mentioned as an absence in the original ZIP but is **not** an approved requirement here. Do not infer it is owed.
