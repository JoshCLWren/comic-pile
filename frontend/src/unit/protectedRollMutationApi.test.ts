import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../query/queryClient'
import { createProtectedRollMutationApi } from '../services/protectedRollMutationApi'
import {
  resetRollPendingSelectionMemory,
  writePendingSelection,
} from '../services/rollPendingSelection'
import { createHttpClientStub } from './httpClientStub'

describe('protected Roll mutation service', () => {
  beforeEach(() => {
    queryClient.clear()
    resetRollPendingSelectionMemory()
    localStorage.clear()
  })

  it('snoozes through the native offer and keeps the full replacement offer', async () => {
    const client = createHttpClientStub()
    client.post.mockResolvedValue({
      thread_id: 7,
      issue_id: 42,
      die_size: 6,
      result: 3,
    })

    const result = await createProtectedRollMutationApi(client).snooze()

    expect(client.post).toHaveBeenCalledWith('/v2/roll/offer', expect.any(Object))
    expect(result).toMatchObject({
      current_die: 6,
      pending_thread_id: 7,
      reading_mode_suggested: false,
      correction: null,
    })
  })

  it('normalizes an offer without a thread to a null pending pointer', async () => {
    const client = createHttpClientStub()
    client.post.mockResolvedValue({
      thread_id: null,
      issue_id: null,
      die_size: 20,
      result: 11,
    })

    const result = await createProtectedRollMutationApi(client).snooze()

    expect(result.pending_thread_id).toBeNull()
    expect(result.current_die).toBe(20)
  })

  it('reconciles recovery from scoped reads with no aggregate or session request', async () => {
    const client = createHttpClientStub()
    client.get.mockImplementation(async (url: string) => {
      if (url === '/v2/roll/eligible-issue-ids') {
        return { issue_ids: [], thread_ids: [], pool_reason: 'empty' }
      }
      if (url === '/v2/issues/9/dependencies') {
        return { issue_id: 9, incoming: [], outgoing: [] }
      }
      throw new Error(`Unexpected GET ${url}`)
    })
    writePendingSelection(42, { issue_id: 9, thread_id: 2, selected_at: 1 })

    const state = await createProtectedRollMutationApi(client).bootstrap(42)

    expect(state.pending_thread_id).toBe(2)
    expect(state.roll_pool).toEqual([])
    expect(state.roll_recovery).toBeNull()
    // The GET stub throws on any URL outside the scoped resources, so an
    // aggregate bootstrap or session read would fail this test.
    expect(client.get).toHaveBeenCalledTimes(2)
  })
})
