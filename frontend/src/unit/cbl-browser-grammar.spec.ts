/**
 * Unit tests for CBL browser grammar fixes
 */

import { describe, expect, test } from 'vitest'

import { countPhraseWithArticle } from '../utils/countPhraseWithArticle'

describe('CBL browser grammar', () => {
  test('correctly handles singular counts', () => {
    expect(countPhraseWithArticle(1, 'entry', 'entries')).toBe('1 entry')
    expect(countPhraseWithArticle(1, 'needs attention', 'need attention')).toBe('1 needs attention')
    expect(countPhraseWithArticle(1, 'issue', 'issues')).toBe('1 issue')
  })

  test('correctly handles plural counts', () => {
    expect(countPhraseWithArticle(2, 'entry', 'entries')).toBe('2 entries')
    expect(countPhraseWithArticle(2, 'needs attention', 'need attention')).toBe('2 need attention')
    expect(countPhraseWithArticle(5, 'issue', 'issues')).toBe('5 issues')
  })

  test('correctly handles zero counts', () => {
    expect(countPhraseWithArticle(0, 'entry', 'entries')).toBe('0 entries')
    expect(countPhraseWithArticle(0, 'needs attention', 'need attention')).toBe('0 need attention')
  })

  test('handles different word types correctly', () => {
    // Test words that don't follow regular pluralization
    expect(countPhraseWithArticle(1, 'series', 'series')).toBe('1 series')
    expect(countPhraseWithArticle(2, 'series', 'series')).toBe('2 series')
    
    // Test regular pluralization
    expect(countPhraseWithArticle(1, 'comic', 'comics')).toBe('1 comic')
    expect(countPhraseWithArticle(2, 'comic', 'comics')).toBe('2 comics')
  })
})