import { describe, expect, it } from 'vitest'

import {
  fromTagTargetType,
  tagTargetTypeUrlSegment,
  toTagTargetType,
} from '../utils/tagTargetType'

describe('toTagTargetType', () => {
  it('maps cache key types to API target types', () => {
    expect(toTagTargetType('issue')).toBe('Issue')
    expect(toTagTargetType('thread')).toBe('Thread')
    expect(toTagTargetType('plan')).toBe('ContinuityPlan')
  })
})

describe('fromTagTargetType', () => {
  it('maps API target types back to cache key types', () => {
    expect(fromTagTargetType('Issue')).toBe('issue')
    expect(fromTagTargetType('Thread')).toBe('thread')
    expect(fromTagTargetType('ContinuityPlan')).toBe('plan')
  })

  it('round-trips with toTagTargetType', () => {
    for (const type of ['issue', 'thread', 'plan'] as const) {
      expect(fromTagTargetType(toTagTargetType(type))).toBe(type)
    }
  })
})

describe('tagTargetTypeUrlSegment', () => {
  it('builds the backend effective-tags URL segment for each target type', () => {
    expect(tagTargetTypeUrlSegment('Issue')).toBe('issue')
    expect(tagTargetTypeUrlSegment('Thread')).toBe('thread')
    expect(tagTargetTypeUrlSegment('ContinuityPlan')).toBe('plan')
  })
})
