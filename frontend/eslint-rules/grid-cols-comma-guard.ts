/**
 * Guard against Tailwind arbitrary `grid-cols-[...]` values that use commas
 * as track separators (issue #2952 failure mode, CI bar owned by #2992).
 *
 * Commas at the top level of a Tailwind arbitrary value are not converted to
 * spaces, so `grid-cols-[1fr,auto]` emits invalid CSS and the grid silently
 * falls back to a single column. The valid spellings use underscores
 * (`grid-cols-[1fr_auto]`) or keep commas only inside CSS functions such as
 * `minmax(0,1fr)` / `repeat(2,minmax(0,1fr))`, where the comma is part of a
 * real CSS function call and must be preserved.
 *
 * This module is the single source of truth shared by the eslint rule in
 * `frontend/eslint.config.ts` and the vitest coverage in
 * `src/unit/grid-cols-comma-guard.test.ts`.
 */

/** Prefix (after responsive/state variants are stripped) this guard inspects. */
const GRID_COLS_ARBITRARY_PREFIX = 'grid-cols-['

/**
 * Strip Tailwind responsive/state variant prefixes (`lg:`, `md:hover:`, …)
 * and return the bare utility token.
 */
function stripVariants(token: string): string {
  const segments = token.split(':')
  return segments[segments.length - 1]
}

/**
 * Find the first class token in `classText` whose `grid-cols-[...]`
 * arbitrary value contains a comma at paren-depth zero, i.e. a comma used
 * as a track separator rather than inside a CSS function call.
 *
 * Returns the offending token, or `null` when the text is clean.
 */
export function findGridColsArbitraryComma(classText: string): string | null {
  const tokens = classText.split(/\s+/)
  for (const token of tokens) {
    const bare = stripVariants(token)
    if (!bare.startsWith(GRID_COLS_ARBITRARY_PREFIX) || !bare.endsWith(']')) {
      continue
    }
    const inner = bare.slice(GRID_COLS_ARBITRARY_PREFIX.length, -1)
    let depth = 0
    for (const ch of inner) {
      if (ch === '(') {
        depth += 1
      } else if (ch === ')') {
        depth = Math.max(0, depth - 1)
      } else if (ch === ',' && depth === 0) {
        return token
      }
    }
  }
  return null
}

/** True when `classText` contains no comma-separated `grid-cols-[...]` value. */
export function hasNoGridColsArbitraryComma(classText: string): boolean {
  return findGridColsArbitraryComma(classText) === null
}

/** Message reported by the eslint rule for an offending token. */
export function gridColsArbitraryCommaMessage(token: string): string {
  return (
    `Invalid Tailwind arbitrary grid-cols value with comma: ${token}. ` +
    'Commas are not converted to spaces inside Tailwind arbitrary values, so this emits ' +
    'invalid CSS and the grid silently collapses (see #2952). Use underscores between ' +
    'tracks (e.g. grid-cols-[1fr_auto]); commas are allowed only inside CSS functions ' +
    'such as minmax(0,1fr).'
  )
}
