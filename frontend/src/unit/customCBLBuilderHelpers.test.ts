import { describe, expect, it } from 'vitest'
import { messageFor, sameEntries } from '../components/customCBLBuilderHelpers'

describe('customCBLBuilderHelpers', () => {
  it('sameEntries returns false when skipped differs', () => {
    const left = [{ id: 1, position: 0, issue_id: 1, thread_id: 1, series_name: 'S', issue_number: '1', status: 'unread' as const, is_checkpoint: false, gate: 'none' as const, skipped: false }]
    const right = [{ id: 1, position: 0, issue_id: 1, thread_id: 1, series_name: 'S', issue_number: '1', status: 'unread' as const, is_checkpoint: false, gate: 'none' as const, skipped: true }]
    expect(sameEntries(left, right)).toBe(false)
  })

  it('sameEntries treats a legacy omitted skipped flag as false', () => {
    const current = [{ id: 1, position: 0, issue_id: 1, thread_id: 1, series_name: 'S', issue_number: '1', status: 'unread' as const, is_checkpoint: false, gate: 'none' as const, skipped: false }]
    const legacy = [{ ...current[0]!, skipped: undefined }] as unknown as typeof current
    expect(sameEntries(current, legacy)).toBe(true)
  })

  it('messageFor prefers decoded detail message', () => {
    const error = { isAxiosError: true, response: { data: { detail: { message: 'Stale write' } } } }
    expect(messageFor(error, 'fallback')).toBe('Stale write')
  })

  it('messageFor falls back to Error.message then fallback', () => {
    expect(messageFor(new Error('boom'), 'fallback')).toBe('boom')
    expect(messageFor({}, 'fallback')).toBe('fallback')
  })
})
