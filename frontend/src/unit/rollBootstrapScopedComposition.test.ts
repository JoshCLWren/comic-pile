import { beforeEach, describe, expect, it } from 'vitest'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import type { IssueCardsResponse } from '../generated/nativeV2Client'
import { createRollBootstrapApi } from '../services/rollBootstrapApi'
import {
  resetRollPendingSelectionMemory,
  writePendingSelection,
} from '../services/rollPendingSelection'
import type { RollLastReadPayload } from '../types'
import { createHttpClientStub } from './httpClientStub'

type IssueCard = IssueCardsResponse['items'][number]

function card(issueId: number, threadId: number, status: string): IssueCard {
  return {
    issue_id: issueId,
    thread_id: threadId,
    thread_title: threadId === 3 ? 'Current Series' : 'Earlier Series',
    issue_number: String(issueId),
    has_confirmed_identity: false,
    mapping_state: 'unmapped',
    status,
  }
}

const LAST_READ: RollLastReadPayload = {
  issue_id: 10,
  issue_number: '10',
  thread_id: 3,
  thread_title: 'Current Series',
  read_at: '2026-11-28T00:00:00.000Z',
}

describe('scoped Roll composition service', () => {
  beforeEach(() => {
    queryClient.clear()
    resetRollPendingSelectionMemory()
    localStorage.clear()
    globalThis.document.cookie =
      'comicpile_roll_snoozes=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
  })

  it('reads the signed-in partition and the scoped last-read cache', async () => {
    const client = createHttpClientStub()
    client.get.mockImplementation(async (url: string) => {
      if (url === '/v2/roll/eligible-issue-ids') {
        return { issue_ids: [10], thread_ids: [3], pool_reason: 'ready' }
      }
      throw new Error(`Unexpected GET ${url}`)
    })
    client.post.mockImplementation(async (url: string) => {
      if (url === '/v2/issues/cards') return { items: [card(10, 3, 'unread')] }
      throw new Error(`Unexpected POST ${url}`)
    })
    queryClient.setQueryData(queryKeys.roll.lastRead(), {
      roll_reconciliation: { last_read: LAST_READ },
    })
    // A different reader's partition must never supply this pending pointer.
    writePendingSelection(99, { issue_id: 77, thread_id: 8, selected_at: 1 })
    writePendingSelection(42, { issue_id: 10, thread_id: 3, selected_at: 2 })

    const state = await createRollBootstrapApi(client).get(42)

    expect(state.pending_thread_id).toBe(3)
    expect(state.last_read).toEqual(LAST_READ)
    expect(state.session_id).toBeUndefined()
  })

  it('composes recovery from one owner-scoped issue-edge read for a blocked pending issue', async () => {
    const client = createHttpClientStub()
    client.get.mockImplementation(async (url: string) => {
      if (url === '/v2/roll/eligible-issue-ids') {
        return { issue_ids: [20], thread_ids: [4], pool_reason: 'ready' }
      }
      if (url === '/v2/issues/10/dependencies') {
        return {
          issue_id: 10,
          incoming: [{
            dependency_id: 55,
            source_issue_id: 9,
            source_issue_number: '3',
            source_thread_id: 7,
            source_thread_title: 'Earlier Series',
          }],
          outgoing: [],
        }
      }
      throw new Error(`Unexpected GET ${url}`)
    })
    client.post.mockImplementation(async (url: string, body?: { issue_ids: number[] }) => {
      if (url === '/v2/issues/cards') {
        return {
          items: body?.issue_ids.includes(9)
            ? [card(9, 7, 'unread')]
            : [card(20, 4, 'unread')],
        }
      }
      throw new Error(`Unexpected POST ${url}`)
    })
    writePendingSelection(42, { issue_id: 10, thread_id: 3, selected_at: 2 })

    const state = await createRollBootstrapApi(client).get(42)

    expect(state.roll_recovery).toMatchObject({
      original_thread_id: 3,
      direct_blockers: [{ source_id: 9, satisfied: false }],
      readable_prerequisites: [{ node_id: 9 }],
    })
  })

  it('composes an empty pool without a card batch, snooze list or recovery read', async () => {
    const client = createHttpClientStub()
    client.get.mockImplementation(async (url: string) => {
      if (url === '/v2/roll/eligible-issue-ids') {
        return { issue_ids: [], thread_ids: [], pool_reason: 'no_eligible_issues' }
      }
      throw new Error(`Unexpected GET ${url}`)
    })

    const state = await createRollBootstrapApi(client).get(42)

    expect(state.roll_pool).toEqual([])
    expect(state.pool_reason).toBe('no_eligible_issues')
    expect(state.roll_recovery).toBeNull()
    expect(state.last_read).toBeNull()
    expect(client.post).not.toHaveBeenCalled()
  })

  it('applies the browser snooze cookie to the scoped pool and snooze shelf', async () => {
    globalThis.document.cookie = 'comicpile_roll_snoozes=%5B9%5D'
    const client = createHttpClientStub()
    client.get.mockImplementation(async (url: string) => {
      if (url === '/v2/roll/eligible-issue-ids') {
        return { issue_ids: [10], thread_ids: [3], pool_reason: 'ready' }
      }
      if (url === '/v2/threads') {
        return {
          threads: [
            { id: 9, title: 'Snoozed Series', format: 'Comic' },
            { id: 8, title: 'Unrelated Series', format: 'Comic' },
          ],
        }
      }
      throw new Error(`Unexpected GET ${url}`)
    })
    client.post.mockImplementation(async (url: string) => {
      if (url === '/v2/issues/cards') return { items: [card(10, 3, 'unread')] }
      throw new Error(`Unexpected POST ${url}`)
    })

    const state = await createRollBootstrapApi(client).get(42)

    expect(state.snoozed_thread_ids).toEqual([9])
    expect(state.snoozed_threads).toEqual([{
      id: 9, title: 'Snoozed Series', format: 'Comic',
    }])
  })

  it('does not request prerequisite cards when a blocked pending issue has no edges', async () => {
    const client = createHttpClientStub()
    client.get.mockImplementation(async (url: string) => {
      if (url === '/v2/roll/eligible-issue-ids') {
        return { issue_ids: [20], thread_ids: [4], pool_reason: 'ready' }
      }
      if (url === '/v2/issues/10/dependencies') {
        return { issue_id: 10, incoming: [], outgoing: [] }
      }
      throw new Error(`Unexpected GET ${url}`)
    })
    client.post.mockImplementation(async (url: string) => {
      if (url === '/v2/issues/cards') return { items: [card(20, 4, 'unread')] }
      throw new Error(`Unexpected POST ${url}`)
    })
    writePendingSelection(42, { issue_id: 10, thread_id: 3, selected_at: 2 })

    const state = await createRollBootstrapApi(client).get(42)

    // The visible face batch is still issued; no second batch for prerequisites.
    expect(client.post).toHaveBeenCalledTimes(1)
    expect(state.roll_recovery).toBeNull()
  })
})
