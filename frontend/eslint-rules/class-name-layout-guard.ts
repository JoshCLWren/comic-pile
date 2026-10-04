/**
 * Guard against class-name string assertions used as evidence of responsive
 * layout correctness (issue #3061).
 *
 * #2949 claimed the Roll layout was responsive while its tests only asserted
 * Tailwind substrings; #2963 then showed the classes themselves were invalid,
 * because a nonexistent or malformed utility still satisfies `toContain`.
 * #2995 moved the real coverage to rendered geometry in Chromium.
 *
 * The remaining gap is preventing future layout work from falling back to
 * class-string evidence. This module is the single source of truth shared by
 * the eslint rule in `frontend/eslint.config.ts` and the vitest coverage in
 * `src/unit/class-name-layout-guard.test.ts`.
 *
 * Scope is deliberately narrow: only a class assertion whose expected value
 * carries a *breakpoint variant* (`sm:`/`md:`/`lg:`/`xl:`/`2xl:`) of a
 * *layout-geometry utility* is rejected. That keeps the ban on responsive
 * layout evidence while leaving semantic state hooks (`disabled`, `loading`),
 * unvarianted utilities that are legitimately part of a component's contract,
 * and non-geometry styling (`text-red-500`, `bg-white`) alone.
 */

/** Tailwind breakpoint variants that make a class assertion breakpoint evidence. */
const RESPONSIVE_PREFIXES = ['sm', 'md', 'lg', 'xl', '2xl']

/** Standalone layout utilities; matched as the whole bare token. */
const LAYOUT_UTILITIES = new Set([
  'absolute',
  'block',
  'contents',
  'fixed',
  'flex',
  'flow-root',
  'grid',
  'hidden',
  'inline',
  'inline-block',
  'inline-flex',
  'inline-grid',
  'invisible',
  'isolate',
  'relative',
  'static',
  'sticky',
  'table',
  'visible',
])

/** Layout-geometry utility families; matched as a prefix of the bare token. */
const LAYOUT_UTILITY_PREFIXES = [
  'aspect-',
  'auto-cols-',
  'auto-rows-',
  'basis-',
  'col-end-',
  'col-span-',
  'col-start-',
  'content-',
  'flex-',
  'gap-',
  'gap-x-',
  'gap-y-',
  'grid-cols-',
  'grid-flow-',
  'grid-rows-',
  'grow',
  'h-',
  'inset-',
  'items-',
  'justify-',
  'left-',
  'm-',
  'max-h-',
  'max-w-',
  'me-',
  'min-h-',
  'min-w-',
  'ml-',
  'mr-',
  'ms-',
  'mt-',
  'mx-',
  'my-',
  'order-',
  'overflow-',
  'overflow-x-',
  'overflow-y-',
  'p-',
  'pb-',
  'pe-',
  'place-',
  'pl-',
  'pr-',
  'ps-',
  'pt-',
  'px-',
  'py-',
  'right-',
  'row-end-',
  'row-span-',
  'row-start-',
  'self-',
  'shrink',
  'size-',
  'space-x-',
  'space-y-',
  'top-',
  'w-',
  'z-',
]

/**
 * Assertion shapes that read a class name as the contract under test.
 *
 * The first entry covers `expect(el).toHaveClass('lg:hidden')` and the
 * Playwright spelling `await expect(locator).not.toHaveClass('lg:hidden')`.
 * The second covers `expect(el.className).toContain('lg:grid')` and its
 * `not.`, `toMatch`, and optional-chaining variants.
 */
const CLASS_ASSERTION_PATTERNS: RegExp[] = [
  /\.?\s*(?:not\s*\.\s*)?toHaveClass\s*\(\s*(['"`])((?:[^'"`\\]|\\.)*)\1/g,
  /\.className\s*\)?\s*\.\s*(?:not\s*\.\s*)?(?:toContain|toMatch|includes)\s*\(\s*(['"`])((?:[^'"`\\]|\\.)*)\1/g,
]

/** A rejected class assertion. */
export interface LayoutClassAssertionFinding {
  /** Responsive layout class tokens that made the assertion layout evidence. */
  tokens: string[]
  /** The assertion call source, trimmed, for the report message. */
  snippet: string
}

/**
 * Return the bare utility token after removing every Tailwind variant prefix.
 */
function bareUtility(token: string): string {
  const segments = token.split(':')
  return segments[segments.length - 1]
}

/**
 * True when any variant in the token's prefix chain is a Tailwind breakpoint.
 */
function hasResponsiveVariant(token: string): boolean {
  const variants = token.split(':').slice(0, -1)
  return variants.some((variant) => RESPONSIVE_PREFIXES.includes(variant))
}

/**
 * True when the bare utility controls rendered geometry, overlap, visibility,
 * stacking, clipping, or flow. Purely presentational utilities such as colors,
 * typography, radii, and borders are deliberately excluded.
 */
export function isLayoutGeometryUtility(token: string): boolean {
  const bare = bareUtility(token)
  if (LAYOUT_UTILITIES.has(bare)) {
    return true
  }
  return LAYOUT_UTILITY_PREFIXES.some((prefix) => bare.startsWith(prefix))
}

/**
 * Collect every class token in `classText` that makes the string responsive
 * layout evidence.
 */
export function findLayoutClassTokens(classText: string): string[] {
  return classText
    .split(/\s+/)
    .filter((token) => token.length > 0 && hasResponsiveVariant(token) && isLayoutGeometryUtility(token))
}

/**
 * Inspect one assertion call's source text and report it when the expected
 * value is a class string carrying responsive layout utilities.
 *
 * Returns `null` for geometry assertions, non-class assertions, semantic state
 * hooks, and any assertion whose expected text is not responsive layout
 * evidence.
 */
export function findLayoutClassAssertion(callText: string): LayoutClassAssertionFinding | null {
  for (const pattern of CLASS_ASSERTION_PATTERNS) {
    pattern.lastIndex = 0
    let match = pattern.exec(callText)
    while (match !== null) {
      const tokens = findLayoutClassTokens(match[2])
      if (tokens.length > 0) {
        return { tokens, snippet: callText.trim() }
      }
      match = pattern.exec(callText)
    }
  }
  return null
}

/** True when the assertion call is class-name layout evidence. */
export function isLayoutClassAssertion(callText: string): boolean {
  return findLayoutClassAssertion(callText) !== null
}

/** Message reported by the eslint rule for a rejected assertion. */
export function layoutClassAssertionMessage(finding: LayoutClassAssertionFinding): string {
  return (
    `Responsive layout class-name assertion: ${finding.snippet}. ` +
    `Responsive layout utilities (${finding.tokens.join(', ')}) are not layout evidence for #3061: ` +
    'a nonexistent or malformed utility still satisfies a string assertion, so these tests pass ' +
    'while the rendered layout is broken (#2949, #2963). Assert rendered geometry in Chromium ' +
    '(bounding boxes, rectangle intersection, viewport containment, computed visibility) as in ' +
    'src/test/issue-2942-roll-layout-invariants.spec.ts, or assert a computed style that survives ' +
    'a broken utility. See frontend/docs/CLASS_NAME_LAYOUT_GUARD.md.'
  )
}
