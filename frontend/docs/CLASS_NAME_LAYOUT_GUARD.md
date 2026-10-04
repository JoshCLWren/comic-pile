# Responsive layout evidence guard

Issue #3061: a class-name string is not layout evidence.

## The failure this prevents

#2949 claimed the Roll layout was responsive and regression-proof while its tests
only asserted Tailwind substrings. #2963 then showed the layout was still broken,
because the classes themselves were invalid.

The root cause is that a class-name assertion passes on an element whose CSS was
never generated:

```tsx
<div className="lg:grid lg:grid-cols-[this_is_not_valid_css] lg:max-w-4xl" />
```

```ts
// Passes while the grid collapses to a single column.
expect(grid.className).toContain('lg:grid')
expect(grid.className).toContain('lg:grid-cols-[this_is_not_valid_css]')
expect(grid.className).toContain('lg:max-w-4xl')
```

Utility validity is not the failure mode either. `lg:grid-cols-1` is a real
Tailwind utility that still proves nothing about the rendered layout, so the
guard rejects it too.

#2995 added the correct evidence: rendered geometry measured in Chromium. This
guard stops new layout work from falling back to class strings.

## What is rejected

A class assertion whose expected value contains a **breakpoint variant**
(`sm:`, `md:`, `lg:`, `xl:`, `2xl:`) of a **layout-geometry utility**:

```ts
// Rejected: breakpoint layout evidence proven only by a string.
expect(grid.className).toContain('lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]')
expect(grid.className).toContain('lg:max-w-4xl')
expect(grid.className).toContain('lg:mx-auto')
expect(element).toHaveClass('lg:hidden')
expect(section).toHaveClass('md:grid-cols-2')
expect(card).not.toHaveClass('md:flex-row')
expect(cell.className).not.toContain('md:row-span-2')
await expect(locator).not.toHaveClass('xl:grid-cols-[repeat(auto-fit,minmax(0,1fr))]')
```

Layout-geometry utilities are the flow and box families: `grid`, `flex`,
`hidden`, `block`, `inline-*`, `items-*`, `justify-*`, `grid-cols-*`,
`row-span-*`, `col-span-*`, `gap-*`, `p*`/`m*`, `w-`/`h-`/`min-*`/`max-*`,
`overflow-*`, `position`, `z-*`, `basis-*`, `grow`, `shrink`, `order-*`.

## What stays legal

The class is still a legitimate contract when the class is not rendered-layout
evidence:

```ts
// Legal: semantic state hooks.
expect(element).toHaveClass('disabled')
expect(button).toHaveClass('loading')
expect(component).toHaveClass('selected')

// Legal: presentational utilities, including breakpoint colors and borders.
expect(element.className).toContain('text-red-500')
expect(badge.className).toContain('md:text-lg')
expect(divider.className).toContain('lg:border-t')
expect(panel.className).toContain('xl:rounded-lg')

// Legal: unvarianted utilities that are the stated contract of the unit test.
expect(comicRegion.className).toContain('min-w-0')
expect(grid.className).toContain('items-start')
expect(wrapper.className).toContain('p-3')
```

## Layout evidence must be measured in a browser

**jsdom cannot prove layout.** It has no layout engine and does not load the
Tailwind stylesheet, so inside `src/unit/` tests:

- `getBoundingClientRect()` returns all zeros,
- `getComputedStyle(el).display` stays at the user-agent default (`block`),
- `minWidth` resolves to `auto` and `gridColumnSpan` is not even implemented,
- any width/height ratio divides by zero and yields `NaN`.

A jsdom assertion written in the shape of the examples below passes or fails for
reasons unrelated to the layout, so it is not evidence and must not be written:

```ts
// Not evidence, in any environment without real layout.
expect(gridStyle.display).toBe('grid')
expect(gridStyle.gridTemplateColumns).toBe('minmax(0,24rem) minmax(18rem,24rem)')
expect(comicRect.width).toBeGreaterThan(0)
```

Measure geometry in the Chromium specs under `src/test/`, where a real engine and
the built stylesheet are present:

```ts
const comic = page.getByTestId('rating-region-comic')
const decision = page.getByTestId('rating-region-decision')
const comicBox = await comic.boundingBox()
const decisionBox = await decision.boundingBox()

// Side by side, not stacked: the decision region starts below the comic one.
expect(decisionBox.y).toBeGreaterThanOrEqual(comicBox.y + comicBox.height - TOLERANCE_PX)

// Contained in the viewport.
expect(comicBox.x).toBeGreaterThanOrEqual(0)
expect(comicBox.x + comicBox.width).toBeLessThanOrEqual(viewport.width)

// No overlap.
expect(intersectionArea(comicBox, decisionBox)).toBe(0)
```

Reference implementations already in the repository:

- `src/test/issue-2942-roll-layout-invariants.spec.ts` — bounding boxes,
  overflow, and pillar ordering across a viewport matrix
- `src/test/issue-2919-roll-desktop-layout-overlap.spec.ts` — overlap and
  intersection
- `src/test/roll-layout-containment.spec.ts` — viewport containment
- `src/test/issue-2023-responsive-app-shell.spec.ts` — breakpoint behavior

## CI enforcement

The rule is `no-layout-class-assertions` in `frontend/eslint.config.ts`, backed
by the pure detector in `frontend/eslint-rules/class-name-layout-guard.ts`. The
same detector is covered by `src/unit/class-name-layout-guard.test.ts`, so the
unit suite fails if the predicate regresses.

```bash
cd frontend && pnpm run lint
```

`pnpm run lint` runs in the `Frontend Lint + Typecheck` CI job, and `pnpm test`
runs the detector coverage in the `Frontend Unit Tests (vitest)` job, so both
halves of the rule are gated by CI.

### Legacy exemption list

Nine pre-existing test files still assert responsive layout through class strings.
They are exempted by `LEGACY_LAYOUT_CLASS_ASSERTION_FILES` in
`frontend/eslint.config.ts`, following the same per-rule ratchet that
`.oxlintrc.json` documents for `anti-slop/*`: the rule is enforced everywhere
else today, and each entry is expected to move its layout contract into
rendered-geometry Chromium coverage before it is removed from the list. New test
files are enforced immediately.

### Writing tests for this guard

The rule reads the source text of each assertion call, so a fixture that embeds a
rejected assertion *inside a real call* reports itself. Keep rejected fixtures in
constant declarations or array literals and pass them by reference:

```ts
const ROLL_GRID_ASSERTION = `expect(grid.className).toContain('lg:max-w-4xl')`

expect(isLayoutClassAssertion(ROLL_GRID_ASSERTION)).toBe(true)
```
