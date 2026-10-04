import { describe, expect, it } from 'vitest'
import {
  findLayoutClassAssertion,
  findLayoutClassTokens,
  isLayoutClassAssertion,
  isLayoutGeometryUtility,
  layoutClassAssertionMessage,
} from '../../eslint-rules/class-name-layout-guard'

/**
 * Issue #3061: reject class-name string assertions as evidence of responsive
 * layout correctness, and keep rendered-geometry tests legal.
 *
 * The fixtures below are source strings, not rendered DOM, on purpose. jsdom has
 * no layout engine and does not load Tailwind, so `getBoundingClientRect()`
 * always returns zeros and `getComputedStyle().display` stays at the user-agent
 * default; a jsdom unit test can never prove geometry. The guard therefore
 * rejects the class-string pattern at lint time and points authors at the
 * Chromium specs under `src/test/`, where rendered geometry is measurable.
 *
 * Every fixture is bound to a constant before use. The eslint rule reads the
 * source text of each assertion call, so embedding a rejected assertion inside
 * an `expect(...)` call here would make this file report itself.
 */

/** #2949 shape: responsive layout proven only by class strings. */
const ROLL_GRID_ASSERTION = `expect(grid!.className).toContain('lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]')`
const INVALID_UTILITY_ASSERTION = `expect(container.className).toContain('lg:grid-cols-[this_is_not_valid_css]')`
const NONEXISTENT_UTILITY_ASSERTION = `expect(container.className).toContain('lg:grid-cols-[nonexistent-class-syntax]')`
const INVALID_SYNTAX_ASSERTION = `expect(container.className).toContain('lg:grid-cols-[invalid_syntax]')`
const VALID_UTILITY_ASSERTION = `expect(container.className).toContain('lg:grid-cols-1')`
const MIXED_CLASS_ASSERTION = `expect(grid.className).toContain('min-w-0 lg:max-w-4xl text-red-500')`

const REJECTED_LAYOUT_ASSERTIONS = [
  ROLL_GRID_ASSERTION,
  `expect(grid!.className).toContain('lg:max-w-4xl')`,
  `expect(grid!.className).toContain('lg:mx-auto')`,
  `expect(grid.className).toMatch('xl:grid-cols-2')`,
  `expect(element).toHaveClass('lg:hidden')`,
  `expect(section).toHaveClass('md:grid-cols-2')`,
  `expect(wrapper).toHaveClass('md:flex-row')`,
  `expect(card).not.toHaveClass('md:flex-row')`,
  `expect(cell.className).not.toContain('md:row-span-2')`,
  `expect(card.className).not.toContain('xl:col-span-full')`,
  `expect(screen.getByTestId('rating-pillars-grid').className).toContain('lg:grid')`,
  `await expect(locator).not.toHaveClass('xl:grid-cols-[repeat(auto-fit,minmax(0,1fr))]')`,
  INVALID_UTILITY_ASSERTION,
  NONEXISTENT_UTILITY_ASSERTION,
  INVALID_SYNTAX_ASSERTION,
  VALID_UTILITY_ASSERTION,
]

/** #2995 shape: rendered geometry as layout evidence. */
const GEOMETRY_ASSERTIONS = [
  `const comicRect = comicRegion.getBoundingClientRect()`,
  `expect(comicRect.width).toBeGreaterThan(0)`,
  `expect(comicRect.width).toBeLessThanOrEqual(1024)`,
  `expect(decisionRect.top).toBeGreaterThan(comicRect.bottom)`,
  `expect(cardRect.bottom).toBeLessThanOrEqual(disclosureRect.top)`,
  `expect(containerRect.left).toBeGreaterThanOrEqual(0)`,
  `expect(containerRect.right).toBeLessThanOrEqual(viewportWidth)`,
  `expect(comicRect.width).toBeGreaterThan(decisionRect.width)`,
  `expect(gridStyle.display).toBe('grid')`,
  `expect(gridStyle.gridTemplateColumns).toBe('minmax(0,24rem) minmax(18rem,24rem)')`,
  `expect(gridStyle.maxWidth).toBe('1024px')`,
  `expect(elementStyle.visibility).toBe('hidden')`,
  `expect(grid!.className).toContain(ROLL_WORKSPACE_MAX_WIDTH)`,
  `expect(grid!.className).toContain(ROLL_WORKSPACE_TRACKS)`,
]

/** Class assertions whose class is the contract, not rendered layout. */
const ALLOWED_CLASS_ASSERTIONS = [
  `expect(element).toHaveClass('disabled')`,
  `expect(button).toHaveClass('loading')`,
  `expect(component).toHaveClass('selected')`,
  `expect(card).toHaveClass('is-open')`,
  `expect(row).not.toHaveClass('aria-busy')`,
  `expect(element).toHaveClass('bg-white')`,
  `expect(element.className).toContain('text-red-500')`,
  `expect(badge.className).toContain('md:text-lg')`,
  `expect(divider.className).toContain('lg:border-t')`,
  `expect(panel.className).toContain('xl:rounded-lg')`,
  `expect(wrapper.className).toContain('p-3')`,
  `expect(comicRegion.className).toContain('min-w-0')`,
  `expect(grid.className).toContain('items-start')`,
  `expect(list.className).toContain('grid')`,
]

/** Source that is not a class assertion at all. */
const NON_ASSERTION_SOURCES = [
  `const grid = screen.getByTestId('rating-pillars-grid')`,
  `<div className="lg:grid lg:grid-cols-2 lg:max-w-4xl" />`,
  `expect(queries.findByRole('grid')).toBeInTheDocument()`,
  `expect(console.warn).not.toHaveBeenCalled()`,
  `const classList = new Set(['lg:hidden'])`,
]

describe('rejects the #2949 shape: responsive layout proven only by class strings', () => {
  it('rejects every responsive layout class assertion', () => {
    for (const assertion of REJECTED_LAYOUT_ASSERTIONS) {
      expect(isLayoutClassAssertion(assertion), assertion).toBe(true)
    }
  })

  it('reports the offending responsive utilities and the assertion source', () => {
    const finding = findLayoutClassAssertion(ROLL_GRID_ASSERTION)
    expect(finding?.tokens).toEqual([
      'lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]',
    ])
    expect(finding?.snippet).toBe(ROLL_GRID_ASSERTION)
  })

  it('reports only the layout tokens when legitimate classes share the string', () => {
    expect(findLayoutClassAssertion(MIXED_CLASS_ASSERTION)?.tokens).toEqual(['lg:max-w-4xl'])
  })
})

describe('accepts the #2995 shape: rendered geometry as layout evidence', () => {
  it('accepts bounding-box, containment, and computed-style assertions', () => {
    for (const assertion of GEOMETRY_ASSERTIONS) {
      expect(isLayoutClassAssertion(assertion), assertion).toBe(false)
    }
  })
})

describe('shows why the rule exists: invalid utilities still satisfy class assertions', () => {
  it('rejects nonexistent and malformed responsive utilities with an actionable message', () => {
    // These are the exact #2963 spellings. A nonexistent or malformed utility is
    // still an attribute value on the element, so each assertion passes while
    // the rendered grid collapses to a single column.
    const finding = findLayoutClassAssertion(INVALID_UTILITY_ASSERTION)
    if (finding === null) {
      throw new Error('expected the guard to reject a nonexistent responsive utility')
    }
    const message = layoutClassAssertionMessage(finding)
    expect(message).toContain('lg:grid-cols-[this_is_not_valid_css]')
    expect(message).toContain('#3061')
    expect(message).toContain('issue-2942-roll-layout-invariants.spec.ts')
    expect(message).toContain('frontend/docs/CLASS_NAME_LAYOUT_GUARD.md')
  })

  it('rejects valid responsive utilities too, because validity is not the failure mode', () => {
    // `lg:grid-cols-1` is a real Tailwind utility and still only proves a
    // string, so the rule targets evidence quality rather than syntax validity.
    expect(isLayoutClassAssertion(VALID_UTILITY_ASSERTION)).toBe(true)
  })
})

describe('does not ban legitimate class assertions unrelated to visual geometry', () => {
  it('allows semantic state hooks, presentational utilities, and stated contracts', () => {
    for (const assertion of ALLOWED_CLASS_ASSERTIONS) {
      expect(isLayoutClassAssertion(assertion), assertion).toBe(false)
    }
  })

  it('ignores source text that merely mentions layout classes', () => {
    for (const source of NON_ASSERTION_SOURCES) {
      expect(isLayoutClassAssertion(source), source).toBe(false)
    }
  })
})

describe('token classification', () => {
  it('reads every breakpoint in a multi-variant token', () => {
    expect(findLayoutClassTokens('md:hover:flex lg:grid')).toEqual(['md:hover:flex', 'lg:grid'])
    expect(findLayoutClassTokens('hover:flex')).toEqual([])
  })

  it('classifies layout utilities by exact token or family prefix', () => {
    expect(isLayoutGeometryUtility('lg:grid')).toBe(true)
    expect(isLayoutGeometryUtility('lg:max-w-4xl')).toBe(true)
    expect(isLayoutGeometryUtility('md:row-span-2')).toBe(true)
    expect(isLayoutGeometryUtility('xl:z-40')).toBe(true)
    expect(isLayoutGeometryUtility('lg:text-red-500')).toBe(false)
    expect(isLayoutGeometryUtility('lg:border-t')).toBe(false)
    expect(isLayoutGeometryUtility('lg:rounded-lg')).toBe(false)
  })

  it('returns an empty token list for class text with no responsive layout utility', () => {
    expect(findLayoutClassTokens('')).toEqual([])
    expect(findLayoutClassTokens('flex items-center')).toEqual([])
    expect(findLayoutClassTokens('lg:bg-white xl:text-sm')).toEqual([])
  })
})
