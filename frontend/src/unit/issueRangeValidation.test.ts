import { describe, expect, it } from 'vitest'
import { validateIssueRangeForStaging } from '../utils/issueParser'

/**
 * Regression coverage for #3586 (consolidating #3633): the Edit Series Add
 * box must never stage a pending issue chip for input that is not an issue.
 */
describe('validateIssueRangeForStaging', () => {
  it('treats an empty or whitespace-only entry as nothing to validate', () => {
    for (const input of ['', '   ', '\t\n']) {
      const result = validateIssueRangeForStaging(input)

      expect(result.valid).toBe(true)
      expect(result.empty).toBe(true)
      expect(result.error).toBeNull()
      expect(result.issues).toEqual([])
    }
  })

  it('accepts issue numbers, ranges, and named forms', () => {
    for (const input of ['19', '0', '19-24', '0-18', 'Annual 1', 'Special 2', '½', 'FCBD 2024', '#19', 'Vol. 2 #5']) {
      const result = validateIssueRangeForStaging(input)

      expect(result.valid, `${input} should be valid`).toBe(true)
      expect(result.error).toBeNull()
      expect(result.issues.length).toBeGreaterThan(0)
    }
  })

  it('accepts numbered labels that still identify an issue', () => {
    for (const input of ['2b', '1.5', '1-Annual', 'Annual 1']) {
      const result = validateIssueRangeForStaging(input)

      expect(result.valid, `${input} should be valid`).toBe(true)
      expect(result.error).toBeNull()
    }
  })

  it('rejects non-numeric garbage such as "abc"', () => {
    const result = validateIssueRangeForStaging('abc')

    expect(result.valid).toBe(false)
    expect(result.empty).toBe(false)
    expect(result.invalidTokens).toEqual(['abc'])
    expect(result.invalidReason).toBe('no-issue-number')
    expect(result.error).toContain("'abc' is not a valid issue number")
    expect(result.error).toContain('Invalid issue')
  })

  it('rejects a negative issue number', () => {
    const result = validateIssueRangeForStaging('-3')

    expect(result.valid).toBe(false)
    expect(result.invalidTokens).toEqual(['-3'])
    expect(result.invalidReason).toBe('negative')
    expect(result.error).toContain('cannot be negative')
  })

  it('rejects a half-written range', () => {
    const result = validateIssueRangeForStaging('19-')

    expect(result.valid).toBe(false)
    expect(result.invalidReason).toBe('malformed-range')
  })

  it('rejects a zero-width entry that would render as an empty issue number', () => {
    const result = validateIssueRangeForStaging('\u200b')

    expect(result.valid).toBe(false)
    expect(result.empty).toBe(false)
    expect(result.invalidReason).toBe('invisible-characters')
    expect(result.error).toContain('invisible characters')
  })

  it('rejects an entry that mixes a valid range with garbage', () => {
    const result = validateIssueRangeForStaging('19-24, abc')

    expect(result.valid).toBe(false)
    expect(result.invalidTokens).toEqual(['abc'])
    expect(result.error).toContain("'abc'")
  })

  it('reports every invalid token when several are present', () => {
    const result = validateIssueRangeForStaging('abc, def')

    expect(result.valid).toBe(false)
    expect(result.invalidTokens).toEqual(['abc', 'def'])
    expect(result.error).toContain("'abc' and 'def'")
  })

  it('surfaces the parser error for an inverted range', () => {
    const result = validateIssueRangeForStaging('25-1')

    expect(result.valid).toBe(false)
    expect(result.error).toContain('cannot exceed')
  })

  it('surfaces the parser error for an oversized range', () => {
    const result = validateIssueRangeForStaging('1-10001')

    expect(result.valid).toBe(false)
    expect(result.error).toContain('Range too large')
  })
})
