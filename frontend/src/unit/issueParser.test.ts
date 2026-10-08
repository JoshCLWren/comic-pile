import { describe, expect, it } from 'vitest'
import { parseIssueRange, parseIssueRangeDetailed } from '../utils/issueParser'

describe('parseIssueRangeDetailed', () => {
  it('warns about unrecognized literal tokens instead of silently accepting them (#3262)', () => {
    const detail = parseIssueRangeDetailed('xyz')

    expect(detail.total).toBe(1)
    expect(detail.issues).toEqual(['xyz'])
    expect(detail.warnings).toEqual([
      "Couldn't parse 'xyz' — it will be created as a literal issue name",
    ])
    expect(detail.breakdown).toEqual([
      { token: 'xyz', type: 'unrecognized-literal', parsedIssues: ['xyz'] },
    ])
  })

  it('warns about decimals that are not valid issue identifiers (#3262)', () => {
    const detail = parseIssueRangeDetailed('1.5')

    expect(detail.total).toBe(1)
    expect(detail.warnings).toHaveLength(1)
    expect(detail.warnings[0]).toContain("Couldn't parse '1.5'")
    expect(detail.breakdown[0].type).toBe('unrecognized-literal')
  })

  it('does not warn for plain numbers, ranges, or known comic naming (#3262)', () => {
    const detail = parseIssueRangeDetailed('1-3, Annual 1, 7, ½, Special 2, Vol. 2 #1')

    expect(detail.warnings).toEqual([])
    expect(detail.total).toBe(8)
    expect(detail.breakdown.map((item) => item.type)).toEqual([
      'range',
      'recognized-literal',
      'number',
      'recognized-literal',
      'recognized-literal',
      'recognized-literal',
    ])
  })

  it('warns about a dashed token that is not a valid integer range (#3262)', () => {
    const detail = parseIssueRangeDetailed('5a-7b')

    expect(detail.total).toBe(1)
    expect(detail.warnings).toEqual([
      "Couldn't parse '5a-7b' — it will be created as a literal issue name",
    ])
    expect(detail.breakdown[0].type).toBe('unrecognized-literal')
  })

  it('reports one warning per unrecognized token and expands ranges in the breakdown (#3262)', () => {
    const detail = parseIssueRangeDetailed('oops, 1-2, wat')

    expect(detail.warnings).toHaveLength(2)
    expect(detail.issues).toEqual(['oops', '1', '2', 'wat'])
    expect(detail.breakdown).toEqual([
      { token: 'oops', type: 'unrecognized-literal', parsedIssues: ['oops'] },
      { token: '1-2', type: 'range', parsedIssues: ['1', '2'] },
      { token: 'wat', type: 'unrecognized-literal', parsedIssues: ['wat'] },
    ])
  })

  it('keeps dedupe and validation behavior unchanged (#3262)', () => {
    expect(parseIssueRangeDetailed('1-2,1-2').issues).toEqual(['1', '2'])
    expect(() => parseIssueRangeDetailed('25-1')).toThrow('cannot exceed')
    expect(() => parseIssueRangeDetailed('')).toThrow('cannot be empty')
    expect(parseIssueRange('1-3, Annual 1, 3')).toBe(4)
  })
})
