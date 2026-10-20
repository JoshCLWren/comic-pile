import { describe, it, expect } from 'vitest'
import { validateIssueRangeForStaging } from '../utils/issueParser'

describe('#3631 Add Series save enforcement (focus)', () => {
  it('rejects unparseable token \"abc\" so save cannot proceed (#3631)', () => {
    const result = validateIssueRangeForStaging('abc')
    expect(result.valid).toBe(false)
    expect(result.invalidTokens).toContain('abc')
  })

  it('accepts valid range \"1-3\"', () => {
    const result = validateIssueRangeForStaging('1-3')
    expect(result.valid).toBe(true)
    expect(result.issues).toEqual(['1', '2', '3'])
  })

  it('accepts recognized literal \"Annual 1\"', () => {
    const result = validateIssueRangeForStaging('Annual 1')
    expect(result.valid).toBe(true)
  })
})
