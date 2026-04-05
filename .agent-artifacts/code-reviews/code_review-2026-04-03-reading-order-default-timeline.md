# Code Review: `fix/reading-order-default-timeline`

## Summary

Two commits: one changes the default reading order view from `graph` to `timeline`, the other documents a CodeRabbit/draft-PR policy in AGENTS.md.

## Issues

### 1. Dead branch in `handleToggleReadingOrder` — Bug (DependencyBuilder.tsx:574-581)

After the change, both branches of the `if/else` inside `setShowReadingOrder` now do the exact same thing:

```tsx
if (next) {
  setReadingView('timeline')  // toggling ON
} else {
  setReadingView('timeline')  // toggling OFF
}
```

This conditional is now pointless. It should either:
- Be collapsed to just `setReadingView('timeline')` with no `if/else`, or
- Have different behavior per branch (e.g., maybe the `else` branch shouldn't set the view at all, since the panel is being hidden).

### 2. Stale preload guard (DependencyBuilder.tsx:583)

```tsx
if (willShowReadingOrder && readingView !== 'graph') {
  await refreshGraphData()
}
```

Since `readingView` is now always set to `'timeline'` before this line runs, the condition `readingView !== 'graph'` is always `true` (assuming the setState has been enqueued). This means `refreshGraphData()` is called every time the reading order is opened, which may be the intended behavior now — but the guard `readingView !== 'graph'` is misleading. If the intent is "always preload graph data when opening," remove the dead guard. If the intent is "don't preload," then this needs rethinking since the state was just set to `'timeline'`.

**Note:** Because `setReadingView` is called inside `setShowReadingOrder`'s updater (batched with React state), `readingView` on line 583 reads the *previous* render's value, not the just-enqueued one. So the guard's behavior depends on what view was active *before* the toggle. This is subtle and worth clarifying with an explicit check or comment.

### 3. Test update looks correct

The test changes correctly reflect the new default: timeline tab is selected on open, timeline panel is visible, flowchart panel is hidden. Removing the intermediate "click to switch to timeline" step is the right call. No issues here.

### 4. AGENTS.md change looks fine

Documenting the non-draft PR default for CodeRabbit is a reasonable policy addition.

## Verdict

**Request changes.** The functional change (default to timeline) is correct in intent, but the implementation leaves dead code that will confuse future readers. Clean up the identical `if/else` branches before merging.

## Response

Addressed.

- `handleToggleReadingOrder()` now sets `showReadingOrder` directly, resets `readingView` to `timeline`, and only preloads graph data when opening.
- The stale `readingView !== 'graph'` guard and duplicated `if/else` branch were removed.
- Focused validation rerun:
  - `cd frontend && npm run typecheck`
  - `cd frontend && npm run build && npx playwright test src/test/readingOrderTimeline.spec.ts`

## Follow-up

Checked again after the fixup push. There is no new review content in this file beyond the original findings above, so no additional code changes were needed at this point.

## Re-review

Verified commit `6e640a88` ("Simplify reading order toggle logic"). Both issues are resolved:

1. Dead `if/else` — replaced with direct `setShowReadingOrder(willShowReadingOrder)` + unconditional `setReadingView('timeline')`. Clean.
2. Stale guard — `readingView !== 'graph'` removed; now just checks `willShowReadingOrder`. Correct.

**Approved.**
