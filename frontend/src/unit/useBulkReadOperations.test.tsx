import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  BULK_READ_OPERATION_KEY_PREFIX,
  bulkReadReceiptKey,
  clearBulkReadReceipt,
  findBulkReadReceipt,
  useBulkReadOperations,
  writeBulkReadReceipt,
} from '../hooks/useBulkReadOperations'
import type { IssueReadOperationResponse } from '../services/api-issues'

function operation(id: number): IssueReadOperationResponse {
  return {
    id,
    operation_type: 'bulk_mark_read',
    created_at: '2026-01-02T03:04:05Z',
    items: [{ issue_id: id, thread_id: 42, issue_number: '1', previous_status: 'unread' }],
  }
}

function fakeApi() {
  return {
    getReadOperation: vi.fn(async (id: number) => operation(id)),
    undoReadOperation: vi.fn(
      async (_id: number): Promise<{ skipped_issue_ids: number[] }> => ({ skipped_issue_ids: [] }),
    ),
  }
}

describe('useBulkReadOperations', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('discovers a persisted operation after reload', async () => {
    window.localStorage.setItem(`${BULK_READ_OPERATION_KEY_PREFIX}42`, '7')
    const api = fakeApi()
    const { result } = renderHook(() => useBulkReadOperations(api))

    await waitFor(() => expect(result.current.operations).toHaveLength(1))
    expect(api.getReadOperation).toHaveBeenCalledWith(7)
    expect(result.current.operations[0]).toEqual({ threadId: 42, operation: operation(7) })
  })

  it('discovers two operations in one series without orphaning either', async () => {
    writeBulkReadReceipt(42, 7)
    writeBulkReadReceipt(42, 8)
    const api = fakeApi()
    const { result } = renderHook(() => useBulkReadOperations(api))

    await waitFor(() => expect(result.current.operations).toHaveLength(2))
    expect(api.getReadOperation).toHaveBeenCalledWith(7)
    expect(api.getReadOperation).toHaveBeenCalledWith(8)

    await act(async () => { await result.current.undo(42, 7) })

    expect(result.current.operations).toHaveLength(1)
    expect(result.current.operations[0].operation.id).toBe(8)
    expect(window.localStorage.getItem(bulkReadReceiptKey(42, 7))).toBeNull()
    expect(window.localStorage.getItem(bulkReadReceiptKey(42, 8))).toBe('1')
  })

  it('finds the most recent receipt for a series and clears only that receipt', () => {
    writeBulkReadReceipt(42, 7)
    writeBulkReadReceipt(42, 8)
    writeBulkReadReceipt(43, 9)

    expect(findBulkReadReceipt(42)?.operationId).toBe(8)
    clearBulkReadReceipt(42, 8)
    expect(findBulkReadReceipt(42)?.operationId).toBe(7)
    expect(window.localStorage.getItem(bulkReadReceiptKey(43, 9))).toBe('1')
  })

  it('picks up a receipt written in another tab through the storage event', async () => {
    const api = fakeApi()
    const { result } = renderHook(() => useBulkReadOperations(api))
    await waitFor(() => expect(result.current.operations).toHaveLength(0))

    await act(async () => {
      window.localStorage.setItem(`${BULK_READ_OPERATION_KEY_PREFIX}42`, '8')
      window.dispatchEvent(new StorageEvent('storage', {
        key: `${BULK_READ_OPERATION_KEY_PREFIX}42`,
        newValue: '8',
      }))
    })

    await waitFor(() => expect(result.current.operations).toHaveLength(1))
    expect(result.current.operations[0].operation.id).toBe(8)
  })

  it('reports partial skips and clears the receipt on undo', async () => {
    window.localStorage.setItem(`${BULK_READ_OPERATION_KEY_PREFIX}42`, '9')
    const api = fakeApi()
    api.undoReadOperation.mockResolvedValueOnce({ skipped_issue_ids: [101] })
    const { result } = renderHook(() => useBulkReadOperations(api))
    await waitFor(() => expect(result.current.operations).toHaveLength(1))

    await act(async () => { await result.current.undo(42, 9) })

    expect(api.undoReadOperation).toHaveBeenCalledWith(9)
    expect(result.current.message).toMatch(/skipped 1 issue/i)
    expect(result.current.operations).toHaveLength(0)
    expect(window.localStorage.getItem(`${BULK_READ_OPERATION_KEY_PREFIX}42`)).toBeNull()
  })

  it('drops receipts for operations that were already undone', async () => {
    window.localStorage.setItem(`${BULK_READ_OPERATION_KEY_PREFIX}42`, '10')
    const api = fakeApi()
    api.getReadOperation.mockResolvedValueOnce({ ...operation(10), undone_at: '2026-01-03T00:00:00Z' })
    const { result } = renderHook(() => useBulkReadOperations(api))

    await waitFor(() => expect(result.current.operations).toHaveLength(0))
    expect(window.localStorage.getItem(`${BULK_READ_OPERATION_KEY_PREFIX}42`)).toBeNull()
  })

  it('discards malformed receipts without calling the API', async () => {
    window.localStorage.setItem(`${BULK_READ_OPERATION_KEY_PREFIX}not-a-thread`, '7')
    window.localStorage.setItem(`${BULK_READ_OPERATION_KEY_PREFIX}42`, 'not-an-id')
    const api = fakeApi()
    const { result } = renderHook(() => useBulkReadOperations(api))

    await waitFor(() => expect(result.current.operations).toHaveLength(0))
    expect(api.getReadOperation).not.toHaveBeenCalled()
    expect(window.localStorage.getItem(`${BULK_READ_OPERATION_KEY_PREFIX}not-a-thread`)).toBeNull()
    expect(window.localStorage.getItem(`${BULK_READ_OPERATION_KEY_PREFIX}42`)).toBeNull()
  })

  it('discards a receipt whose operation can no longer be loaded', async () => {
    window.localStorage.setItem(`${BULK_READ_OPERATION_KEY_PREFIX}42`, '11')
    const api = fakeApi()
    api.getReadOperation.mockRejectedValueOnce(new Error('operation gone'))
    const { result } = renderHook(() => useBulkReadOperations(api))

    await waitFor(() => expect(window.localStorage.getItem(`${BULK_READ_OPERATION_KEY_PREFIX}42`)).toBeNull())
    expect(result.current.operations).toHaveLength(0)
  })

  it('reports a failed undo while keeping the receipt for a retry', async () => {
    window.localStorage.setItem(`${BULK_READ_OPERATION_KEY_PREFIX}42`, '12')
    const api = fakeApi()
    api.undoReadOperation.mockRejectedValueOnce(new Error('network'))
    const { result } = renderHook(() => useBulkReadOperations(api))
    await waitFor(() => expect(result.current.operations).toHaveLength(1))

    await act(async () => { await result.current.undo(42, 12) })

    expect(result.current.message).toMatch(/failed to undo/i)
    expect(window.localStorage.getItem(`${BULK_READ_OPERATION_KEY_PREFIX}42`)).toBe('12')
    expect(result.current.operations).toHaveLength(1)
  })
})
