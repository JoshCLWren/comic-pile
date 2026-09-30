import { describe, expect, it } from 'vitest'
import {
  findGridColsArbitraryComma,
  gridColsArbitraryCommaMessage,
  hasNoGridColsArbitraryComma,
} from '../../eslint-rules/grid-cols-comma-guard'

/**
 * CI bar for #2992 (part B): the `grid-cols-[...,...]` comma failure mode
 * from #2952 must fail lint while the valid spellings keep passing.
 *
 * These fixtures deliberately avoid writing a literal comma-separated
 * `grid-cols-[...]` token in source: the eslint rule under test scans every
 * string literal in the repo, so the offending shape is assembled with
 * `String.fromCharCode(44)` instead.
 */
const COMMA = String.fromCharCode(44)

function commaTracks(...tracks: string[]): string {
  return `grid-cols-[${tracks.join(COMMA)}]`
}

describe('grid-cols arbitrary comma guard (#2992, bans #2952 failure mode)', () => {
  it('flags a deliberate comma-separated track list', () => {
    expect(findGridColsArbitraryComma(commaTracks('1fr', 'auto'))).toBe(
      commaTracks('1fr', 'auto'),
    )
    expect(hasNoGridColsArbitraryComma(commaTracks('1fr', 'auto'))).toBe(false)
  })

  it('flags comma tracks behind responsive/state variants', () => {
    expect(findGridColsArbitraryComma(`lg:${commaTracks('auto', '1fr')}`)).not.toBeNull()
    expect(
      findGridColsArbitraryComma(`ordinary ${commaTracks('1fr', 'auto')} classes`),
    ).not.toBeNull()
    expect(hasNoGridColsArbitraryComma(`md:hover:${commaTracks('1fr', 'auto')}`)).toBe(
      false,
    )
  })

  it('flags a comma after a CSS function as well as a bare comma', () => {
    const nested = `grid-cols-[minmax(0${COMMA}1fr)${COMMA}auto]`
    expect(findGridColsArbitraryComma(nested)).toBe(nested)
  })

  it('ignores incomplete tokens without a closing bracket', () => {
    expect(hasNoGridColsArbitraryComma('grid-cols-[1fr')).toBe(true)
    expect(hasNoGridColsArbitraryComma('grid-cols-2')).toBe(true)
  })

  it('passes the underscore form that #2990-era code uses', () => {
    expect(findGridColsArbitraryComma('grid items-start gap-4 lg:grid-cols-[1fr_auto] lg:gap-6')).toBeNull()
    expect(hasNoGridColsArbitraryComma('lg:grid-cols-[auto_1fr]')).toBe(true)
    expect(hasNoGridColsArbitraryComma('sm:grid-cols-[minmax(0,1fr)_auto]')).toBe(true)
  })

  it('passes commas nested inside CSS functions such as minmax/repeat', () => {
    expect(hasNoGridColsArbitraryComma('md:grid-cols-[auto_minmax(0,1fr)]')).toBe(true)
    expect(
      hasNoGridColsArbitraryComma('sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]'),
    ).toBe(true)
    expect(
      hasNoGridColsArbitraryComma('xl:grid-cols-[repeat(auto-fit,minmax(12rem,1fr))]'),
    ).toBe(true)
  })

  it('ignores non-grid-cols classes and ordinary commas', () => {
    expect(hasNoGridColsArbitraryComma('grid grid-cols-2 gap-4')).toBe(true)
    expect(hasNoGridColsArbitraryComma('tracking-[0.18em] text-[11px]')).toBe(true)
    expect(hasNoGridColsArbitraryComma('a,b grid-cols-2')).toBe(true)
    expect(hasNoGridColsArbitraryComma('')).toBe(true)
  })

  it('reports an actionable message naming the offending token', () => {
    const token = commaTracks('1fr', 'auto')
    const message = gridColsArbitraryCommaMessage(token)
    expect(message).toContain(token)
    expect(message).toContain('grid-cols-[1fr_auto]')
    expect(message).toContain('#2952')
  })
})
