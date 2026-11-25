import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  BULK_READ_OPERATION_KEY_PREFIX,
  useBulkReadOperations,
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
})
