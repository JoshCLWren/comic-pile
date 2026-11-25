import { beforeEach, describe, expect, it } from 'vitest'
import {
  messageFor,
  restoreReadingListUndo,
  sameEntries,
  writeReadingListUndo,
} from '../components/customCBLBuilderHelpers'

describe('customCBLBuilderHelpers', () => {
  beforeEach(() => window.sessionStorage.clear())
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

  it('restores Undo only for the same owner, list, and saved version', () => {
    const snapshot = {
      baseline: '2026-11-20T00:05:00Z',
      payload: { name: 'Julix', description: null, mode: 'strict' as const, issue_ids: [2, 1] },
    }
    writeReadingListUndo(1, 2, snapshot)
    expect(restoreReadingListUndo(1, 2, snapshot.baseline)).toEqual(snapshot)
    expect(restoreReadingListUndo(2, 2, snapshot.baseline)).toBeNull()
    expect(restoreReadingListUndo(1, 3, snapshot.baseline)).toBeNull()
    expect(restoreReadingListUndo(1, 2, '2026-11-20T00:06:00Z')).toBeNull()
    expect(restoreReadingListUndo(1, 2, snapshot.baseline)).toBeNull()
  })

  it('clears Undo and ignores malformed session data', () => {
    const snapshot = {
      baseline: 'v2',
      payload: { name: 'List', description: null, mode: 'loose' as const, issue_ids: [1] },
    }
    writeReadingListUndo(1, 9, snapshot)
    writeReadingListUndo(1, 9, null)
    expect(restoreReadingListUndo(1, 9, 'v2')).toBeNull()

    for (const stored of ['{', 'null', '{}', '{"baseline":"v2","payload":{"issue_ids":"bad"}}']) {
      window.sessionStorage.setItem('comic-pile:reading-list-undo:1:9', stored)
      expect(restoreReadingListUndo(1, 9, 'v2')).toBeNull()
    }
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
