import { describe, expect, it } from 'vitest'
import {
  isOrdinaryNumericIssueNumber,
  resolveNaturalInsertAnchor,
} from '../utils/issueOrderUtils'

const issue = (id: number, issueNumber: string) => ({ id, issue_number: issueNumber })

describe('isOrdinaryNumericIssueNumber', () => {
  it('accepts ordinary positive issue numbers', () => {
    expect(isOrdinaryNumericIssueNumber('1')).toBe(true)
    expect(isOrdinaryNumericIssueNumber('33')).toBe(true)
    expect(isOrdinaryNumericIssueNumber('250')).toBe(true)
  })

  it('rejects irregular provider numbering', () => {
    expect(isOrdinaryNumericIssueNumber('0')).toBe(false)
    expect(isOrdinaryNumericIssueNumber('-1')).toBe(false)
    expect(isOrdinaryNumericIssueNumber('1.5')).toBe(false)
    expect(isOrdinaryNumericIssueNumber('½')).toBe(false)
    expect(isOrdinaryNumericIssueNumber('Annual 1')).toBe(false)
    expect(isOrdinaryNumericIssueNumber('1MU')).toBe(false)
    expect(isOrdinaryNumericIssueNumber('')).toBe(false)
  })
})

describe('resolveNaturalInsertAnchor', () => {
  it('inserts the reported #2 before #33, #34, #35', () => {
    const existing = [issue(1, '33'), issue(2, '34'), issue(3, '35')]

    expect(resolveNaturalInsertAnchor(existing, '2')).toEqual({ kind: 'start' })
  })

  it('inserts between surrounding issue numbers', () => {
    const existing = [issue(1, '1'), issue(2, '3')]

    expect(resolveNaturalInsertAnchor(existing, '2')).toEqual({ kind: 'after', issueId: 1 })
  })

  it('anchors a gap-filling range after the last lower issue', () => {
    const existing = [issue(1, '1'), issue(2, '2'), issue(3, '10')]

    expect(resolveNaturalInsertAnchor(existing, '4-5')).toEqual({ kind: 'after', issueId: 2 })
  })

  it('produces the same anchor regardless of the typed order', () => {
    const existing = [issue(1, '1'), issue(2, '3')]

    expect(resolveNaturalInsertAnchor(existing, '5,2,4')).toEqual(
      resolveNaturalInsertAnchor(existing, '2,4,5'),
    )
  })

  it('ignores issue numbers that already exist in the thread', () => {
    const existing = [issue(1, '1'), issue(2, '2'), issue(3, '3')]

    // "2" already exists, so only "5" is new and it belongs after issue #3.
    expect(resolveNaturalInsertAnchor(existing, '2-5')).toEqual({ kind: 'after', issueId: 3 })
  })

  it('appends when every requested issue already exists', () => {
    const existing = [issue(1, '1'), issue(2, '2')]

    expect(resolveNaturalInsertAnchor(existing, '1-2')).toEqual({ kind: 'end' })
  })

  it('preserves the canonical order for irregular identifiers', () => {
    const existing = [issue(1, '1'), issue(2, '2'), issue(3, '3')]

    expect(resolveNaturalInsertAnchor(existing, 'Annual 1')).toEqual({ kind: 'end' })
    expect(resolveNaturalInsertAnchor(existing, '0')).toEqual({ kind: 'end' })
    expect(resolveNaturalInsertAnchor(existing, '½')).toEqual({ kind: 'end' })
  })

  it('treats a mixed ordinary and irregular run as ambiguous', () => {
    const existing = [issue(1, '1'), issue(2, '2')]

    expect(resolveNaturalInsertAnchor(existing, '0, 5')).toEqual({ kind: 'end' })
    expect(resolveNaturalInsertAnchor(existing, 'Annual 1, 9')).toEqual({ kind: 'end' })
  })

  it('keeps an intentionally non-numeric prefix where the reader put it', () => {
    const existing = [issue(1, '10'), issue(2, '1'), issue(3, '2')]

    // #3 is added: the last existing ordinary issue below it is #2, not #1.
    expect(resolveNaturalInsertAnchor(existing, '3')).toEqual({ kind: 'after', issueId: 3 })
  })

  it('does not let irregular existing issues capture the anchor', () => {
    const existing = [issue(1, 'Annual 1'), issue(2, '1')]

    expect(resolveNaturalInsertAnchor(existing, '2')).toEqual({ kind: 'after', issueId: 2 })
  })

  it('anchors at the start when no ordinary issue sorts first', () => {
    const existing = [issue(1, 'Annual 1'), issue(2, 'Annual 2')]

    expect(resolveNaturalInsertAnchor(existing, '5')).toEqual({ kind: 'start' })
  })

  it('appends into an empty thread', () => {
    expect(resolveNaturalInsertAnchor([], '1-3')).toEqual({ kind: 'end' })
  })

  it('rejects an invalid range before any request is made', () => {
    const existing = [issue(1, '1')]

    expect(() => resolveNaturalInsertAnchor(existing, '5-2')).toThrow('cannot exceed')
    expect(() => resolveNaturalInsertAnchor(existing, '  ')).toThrow('cannot be empty')
  })
})
