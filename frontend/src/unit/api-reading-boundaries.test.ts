import { describe, expect, it } from 'vitest'
import { createReadingBoundariesApi } from '../services/api-reading-boundaries'
import {
  createRequestRecorder,
  requestedThreadIds,
} from './requestRecorder'

describe('reading boundaries API', () => {
  it('normalizes every row to the legacy authority for a mixed paginated batch', async () => {
    const { calls, client } = createRequestRecorder((call) => {
      const ids = requestedThreadIds(call)
      return {
        evaluator: ids.includes(201) ? 'enabled' : 'unavailable',
        threads: Object.fromEntries(ids.map((id) => [id, {
          thread_id: id,
          state: 'available',
          summary: 'Available now.',
          next: {
            issue: {
              issue_id: id + 1_000,
              issue_number: '1',
              label: 'Stale next issue',
              reading_lists: [],
              thread_id: id,
              thread_title: `Thread ${id}`,
            },
          },
          blockers: [{
            kind: 'strict_order',
            origin: 'reader',
            reason: 'Stale canonical blocker',
            waiting_on: [],
          }],
        }])),
      }
    })

    const result = await createReadingBoundariesApi(client).batch(
      Array.from({ length: 201 }, (_, index) => index + 1),
    )

    expect(result.evaluator).toBe('unavailable')
    expect(Object.keys(result.threads)).toHaveLength(201)
    for (const row of Object.values(result.threads)) {
      expect(row).toMatchObject({
        state: 'unavailable',
        summary: 'The canonical evaluator is unavailable.',
        next: null,
        blockers: [],
      })
    }
    expect(calls.map(requestedThreadIds).map((ids) => ids.length)).toEqual([200, 1])
  })

  it('normalizes available rows from an older response without an evaluator', async () => {
    const { client } = createRequestRecorder(() => ({
      threads: {
        7: {
          thread_id: 7,
          state: 'available',
          summary: 'Available now.',
          next: {
            issue: {
              issue_id: 70,
              issue_number: '1',
              label: 'Stale next issue',
              reading_lists: [],
              thread_id: 7,
              thread_title: 'Thread 7',
            },
          },
          blockers: [],
        },
      },
    }))

    const result = await createReadingBoundariesApi(client).batch([7])

    expect(result).toEqual({
      evaluator: 'unavailable',
      threads: {
        7: {
          thread_id: 7,
          state: 'unavailable',
          summary: 'The canonical evaluator is unavailable.',
          next: null,
          blockers: [],
        },
      },
    })
  })
})
