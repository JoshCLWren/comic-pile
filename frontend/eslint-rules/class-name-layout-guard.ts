/**
 * Guard against DOM class-name assertions as evidence of responsive layout correctness.
 * 
 * Issue #3061: Ban DOM class-name assertions as evidence of responsive layout correctness.
 * 
 * Tests must prove rendered geometry or observable browser outcomes, not just class-name 
 * contents. Class-name assertions are insufficient for layout regression coverage because:
 * 
 * 1. Invalid/nonexistent Tailwind classes can still pass string assertions
 * 2. Class names don't prove actual rendered geometry, overlap, visibility, stacking, etc.
 * 3. Layout behavior should be tested through observable browser measurements
 * 
 * This rule detects problematic patterns in test files:
 * - className assertions containing responsive variants (lg:, md:, xl:)
 * - toContain/toHaveClass calls with Tailwind responsive tokens
 * - String matching that only validates class presence, not actual geometry
 * 
 * Legitimate class assertions (unrelated to visual geometry) are allowed:
 * - Semantic state hooks (e.g., 'disabled', 'loading', 'selected')
 * - Non-responsive visual properties (e.g., colors, spacing without breakpoints)
 * - Component-specific styling that is the actual contract
 * 
 * Detection lives in ./eslint-rules/class-name-layout-guard.ts so the vitest
 * suite can cover the same predicate.
 */

/** Responsive prefixes this guard targets (must match Tailwind breakpoints) */
const RESPONSIVE_PREFIXES = ['sm:', 'md:', 'lg:', 'xl:', '2xl:']

/** Geometry-related class patterns that indicate layout testing */
const GEOMETRY_PATTERNS = [
  'grid-cols',
  'grid-rows', 
  'flex',
  'items-',
  'justify-',
  'space-',
  'p-',
  'm-',
  'gap-',
  'w-',
  'h-',
  'max-w-',
  'max-h-',
  'min-w-',
  'min-h-',
  'col-span',
  'row-span',
  'hidden',
  'block',
  'inline',
  'visible',
  'invisible',
  'overflow-',
  'text-',
  'leading-',
  'rounded-',
  'border-',
]

/** Test assertion methods that indicate class-based layout validation */
const ASSERTION_METHODS = [
  'toHaveClass',
  'toContain',
  'toMatch',
  'not.toHaveClass', 
  'not.toContain',
  'not.toMatch'
]

/**
 * Strip responsive prefixes and return the bare utility token.
 */
function stripResponsivePrefixes(token: string): string {
  const segments = token.split(':')
  return segments[segments.length - 1]
}

/**
 * Check if a token appears to be testing responsive layout geometry.
 */
function isResponsiveLayoutToken(token: string): boolean {
  // Check for responsive prefixes
  const hasResponsivePrefix = RESPONSIVE_PREFIXES.some(prefix => token.startsWith(prefix))
  
  // Check for geometry patterns in the base token
  const baseToken = stripResponsivePrefixes(token)
  const hasGeometryPattern = GEOMETRY_PATTERNS.some(pattern => baseToken.includes(pattern))
  
  return hasResponsivePrefix && hasGeometryPattern
}

/**
 * Find problematic class-name assertions in test code that use
 * responsive layout tokens as evidence of geometry.
 */
export function findResponsiveLayoutClassAssertion(
  code: string, 
  assertionMethod: string
): { problematicTokens: string[], fullMatch: string } | null {
  const lines = code.split('\n')
  
  for (const line of lines) {
    // Look for assertion method calls
    if (line.includes(assertionMethod)) {
      // Extract the className argument
      const classNameMatch = line.match(/(?:className|\.className)\s*(?:\.\s*className)?\s*[\[\(]\s*['"`]([^'"`]+)['"`]/)
      if (!classNameMatch) continue
      
      const classNameContent = classNameMatch[1]
      
      // Check for responsive layout tokens
      const tokens = classNameContent.split(/\s+/)
      const problematicTokens = tokens.filter(token => 
        isResponsiveLayoutToken(token)
      )
      
      if (problematicTokens.length > 0) {
        return {
          problematicTokens,
          fullMatch: line.trim()
        }
      }
    }
  }
  
  return null
}

/**
 * Check if test code contains problematic class-name assertions
 * for responsive layout correctness.
 */
export function hasResponsiveLayoutClassAssertions(code: string): boolean {
  for (const method of ASSERTION_METHODS) {
    const result = findResponsiveLayoutClassAssertion(code, method)
    if (result) {
      return true
    }
  }
  return false
}

/**
 * Generate error message for problematic class-name assertions.
 */
export function responsiveLayoutClassAssertionMessage(
  problematicTokens: string[],
  fullMatch: string
): string {
  return (
    `Responsive layout class-name assertion detected: "${fullMatch}".\n` +
    `Problematic tokens: ${problematicTokens.join(', ')}\n\n` +
    `Class-name assertions are insufficient for layout regression coverage because:\n` +
    `1. Invalid/nonexistent Tailwind classes can still pass string assertions\n` +
    `2. Class names don't prove actual rendered geometry, overlap, visibility, etc.\n` +
    `3. Layout behavior should be tested through observable browser measurements\n\n` +
    `Instead, test rendered geometry using:\n` +
    `- getBoundingClientRect() for dimensions and positioning\n` +
    `- getComputedStyle() for computed styles and visibility\n` +
    `- Intersection Observer API for overlap/visibility\n` +
    `- Viewport containment checks\n` +
    `- Actual content rendering behavior\n\n` +
    `Semantic state hooks (non-geometry) are still allowed.`
  )
}