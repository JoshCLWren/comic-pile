import { describe, expect, it } from 'vitest'
import {
  canSnoozeSeries,
  SNOOZE_REQUIRES_PENDING_SERIES_REASON,
} from '../components/snoozeAvailability'

describe('canSnoozeSeries', () => {
  it('allows snoozing the series the reader rolled this session', () => {
    expect(
      canSnoozeSeries({ threadId: 7, isSnoozed: false, pendingThreadId: 7 }),
    ).toBe(true)
  })

  it('rejects snoozing any other pooled series', () => {
    expect(
      canSnoozeSeries({ threadId: 8, isSnoozed: false, pendingThreadId: 7 }),
    ).toBe(false)
  })

  it('rejects snoozing when nothing is rolled', () => {
    expect(canSnoozeSeries({ threadId: 7, isSnoozed: false, pendingThreadId: null })).toBe(
      false,
    )
    expect(canSnoozeSeries({ threadId: 7, isSnoozed: false, pendingThreadId: undefined })).toBe(
      false,
    )
  })

  it('always allows unsnoozing a series the session already snoozed', () => {
    expect(canSnoozeSeries({ threadId: 8, isSnoozed: true, pendingThreadId: null })).toBe(true)
    expect(canSnoozeSeries({ threadId: 8, isSnoozed: true, pendingThreadId: 7 })).toBe(true)
  })

  it('exposes a stable explanation for an unavailable control', () => {
    expect(SNOOZE_REQUIRES_PENDING_SERIES_REASON).toMatch(/\bsnooz/i)
    expect(SNOOZE_REQUIRES_PENDING_SERIES_REASON.length).toBeGreaterThan(0)
  })
})