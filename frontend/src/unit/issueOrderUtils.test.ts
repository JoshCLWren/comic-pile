/**
 * Tests for issue order utility functions
 */

import { findNaturalInsertPosition, isOrdinaryNumericIssue, parseOrdinaryNumericIssue } from '../utils/issueOrderUtils'

describe('issueOrderUtils', () => {
  describe('isOrdinaryNumericIssue', () => {
    test('returns true for ordinary numeric issues', () => {
      expect(isOrdinaryNumericIssue('1')).toBe(true)
      expect(isOrdinaryNumericIssue('25')).toBe(true)
      expect(isOrdinaryNumericIssue('0')).toBe(true)
      expect(isOrdinaryNumericIssue('100')).toBe(true)
    })

    test('returns false for non-ordinary issues', () => {
      expect(isOrdinaryNumericIssue('Annual 1')).toBe(false)
      expect(isOrdinaryNumericIssue('½')).toBe(false)
      expect(isOrdinaryNumericIssue('-1')).toBe(false)
      expect(isOrdinaryNumericIssue('1a')).toBe(false)
      expect(isOrdinaryNumericIssue('1.5')).toBe(false)
      expect(isOrdinaryNumericIssue('Issue 1')).toBe(false)
    })
  })

  describe('parseOrdinaryNumericIssue', () => {
    test('returns number for ordinary numeric issues', () => {
      expect(parseOrdinaryNumericIssue('1')).toBe(1)
      expect(parseOrdinaryNumericIssue('25')).toBe(25)
      expect(parseOrdinaryNumericIssue('0')).toBe(0)
      expect(parseOrdinaryNumericIssue('100')).toBe(100)
    })

    test('returns null for non-ordinary issues', () => {
      expect(parseOrdinaryNumericIssue('Annual 1')).toBe(null)
      expect(parseOrdinaryNumericIssue('½')).toBe(null)
      expect(parseOrdinaryNumericIssue('-1')).toBe(null)
      expect(parseOrdinaryNumericIssue('1a')).toBe(null)
    })
  })

  describe('findNaturalInsertPosition', () => {
    test('adds #2 to empty list (should append)', () => {
      const existingIssues = []
      const newIssueNumbers = ['2']
      const result = findNaturalInsertPosition(existingIssues, newIssueNumbers)
      expect(result).toBe(null) // Should append when no existing issues
    })

    test('adds #2 to #33,#34,#35 (should insert at beginning)', () => {
      const existingIssues = [
        { id: 1, issue_number: '33' },
        { id: 2, issue_number: '34' },
        { id: 3, issue_number: '35' }
      ]
      const newIssueNumbers = ['2']
      const result = findNaturalInsertPosition(existingIssues, newIssueNumbers)
      expect(result).toBe(null) // Should insert at beginning (null means append to beginning)
    })

    test('adds #2 to #1,#3 (should insert after #1)', () => {
      const existingIssues = [
        { id: 1, issue_number: '1' },
        { id: 2, issue_number: '3' }
      ]
      const newIssueNumbers = ['2']
      const result = findNaturalInsertPosition(existingIssues, newIssueNumbers)
      expect(result).toBe(1) // Should insert after issue with id 1
    })

    test('adds #4,#5 to #1,#2,#10 (should insert after #2)', () => {
      const existingIssues = [
        { id: 1, issue_number: '1' },
        { id: 2, issue_number: '2' },
        { id: 3, issue_number: '10' }
      ]
      const newIssueNumbers = ['4', '5']
      const result = findNaturalInsertPosition(existingIssues, newIssueNumbers)
      expect(result).toBe(2) // Should insert after issue with id 2
    })

    test('adds "Annual 1" to numeric issues (should append - ambiguous case)', () => {
      const existingIssues = [
        { id: 1, issue_number: '1' },
        { id: 2, issue_number: '2' },
        { id: 3, issue_number: '3' }
      ]
      const newIssueNumbers = ['Annual 1']
      const result = findNaturalInsertPosition(existingIssues, newIssueNumbers)
      expect(result).toBe(null) // Should append for ambiguous cases
    })

    test('adds multiple issues with mixed types (should handle numeric naturally)', () => {
      const existingIssues = [
        { id: 1, issue_number: '1' },
        { id: 2, issue_number: '3' },
        { id: 3, issue_number: '5' }
      ]
      const newIssueNumbers = ['2', 'Annual 1', '4']
      const result = findNaturalInsertPosition(existingIssues, newIssueNumbers)
      expect(result).toBe(1) // Should insert after issue #1 (for the numeric '2')
    })

    test('adds issues with existing non-numeric issues (should still work)', () => {
      const existingIssues = [
        { id: 1, issue_number: '1' },
        { id: 2, issue_number: 'Annual 1' },
        { id: 3, issue_number: '3' }
      ]
      const newIssueNumbers = ['2']
      const result = findNaturalInsertPosition(existingIssues, newIssueNumbers)
      expect(result).toBe(1) // Should insert after issue #1 (ignoring non-numeric)
    })

    test('adds issues that should go at the end', () => {
      const existingIssues = [
        { id: 1, issue_number: '1' },
        { id: 2, issue_number: '2' },
        { id: 3, issue_number: '3' }
      ]
      const newIssueNumbers = ['4', '5']
      const result = findNaturalInsertPosition(existingIssues, newIssueNumbers)
      expect(result).toBe(3) // Should insert after last issue (id 3)
    })
  })
})