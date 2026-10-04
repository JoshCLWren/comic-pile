import { describe, expect, it } from 'vitest'
import {
  getMappingStatus,
  getMappingStatusText,
  getMappingStatusDescription,
  needsMappingAttention,
  hasConfirmedMappings,
  getMappingSummary,
} from '../utils/comicVineMapping'
import type { ComicVineMappingHealth } from '../types/comic-vine'

const base: ComicVineMappingHealth = {
  status: 'partial',
  tracked_issue_count: 4,
  confirmed_issue_count: 2,
  needs_mapping_count: 2,
  needs_review_count: 0,
}

describe('comicVineMapping helpers', () => {
  it('getMappingStatus returns null for null input', () => {
    expect(getMappingStatus(null)).toBeNull()
    expect(getMappingStatus(base)).toBe('partial')
  })

  it('getMappingStatusText covers null and every status', () => {
    expect(getMappingStatusText(null)).toBe('')
    expect(getMappingStatusText('not_applicable')).toBe('Not applicable')
    expect(getMappingStatusText('fully_mapped')).toBe('Fully mapped')
    expect(getMappingStatusText('partial')).toBe('Partially mapped')
    expect(getMappingStatusText('unresolved')).toBe('Needs mapping')
    expect(getMappingStatusText('needs_review')).toBe('Needs review')
  })

  it('getMappingStatusDescription covers every status and null', () => {
    expect(getMappingStatusDescription(null)).toBe('')
    expect(getMappingStatusDescription({ ...base, status: 'not_applicable' })).toBe('This series does not use issue tracking')
    expect(getMappingStatusDescription({ ...base, status: 'fully_mapped' })).toBe('4 issues mapped')
    expect(getMappingStatusDescription({ ...base, status: 'partial' })).toBe('2 of 4 issues mapped')
    expect(getMappingStatusDescription({ ...base, status: 'unresolved' })).toBe('4 issues need mapping')
    expect(getMappingStatusDescription({ ...base, status: 'needs_review', needs_review_count: 3 })).toBe('3 issues need review')
  })

  it('needsMappingAttention flags partial, unresolved, needs_review only', () => {
    expect(needsMappingAttention(null)).toBe(false)
    expect(needsMappingAttention({ ...base, status: 'partial' })).toBe(true)
    expect(needsMappingAttention({ ...base, status: 'unresolved' })).toBe(true)
    expect(needsMappingAttention({ ...base, status: 'needs_review' })).toBe(true)
    expect(needsMappingAttention({ ...base, status: 'fully_mapped' })).toBe(false)
    expect(needsMappingAttention({ ...base, status: 'not_applicable' })).toBe(false)
  })

  it('hasConfirmedMappings reflects counts', () => {
    expect(hasConfirmedMappings(null)).toBe(false)
    expect(hasConfirmedMappings({ ...base, confirmed_issue_count: 0 })).toBe(false)
    expect(hasConfirmedMappings(base)).toBe(true)
  })

  it('getMappingSummary covers every status and null', () => {
    expect(getMappingSummary(null)).toBe('')
    expect(getMappingSummary({ ...base, status: 'not_applicable' })).toBe('No mapping needed')
    expect(getMappingSummary({ ...base, status: 'fully_mapped' })).toBe('All issues mapped')
    expect(getMappingSummary({ ...base, status: 'partial' })).toBe('2/4 mapped')
    expect(getMappingSummary({ ...base, status: 'unresolved' })).toBe('2 need mapping')
    expect(getMappingSummary({ ...base, status: 'needs_review', needs_review_count: 5 })).toBe('5 need review')
  })
})
