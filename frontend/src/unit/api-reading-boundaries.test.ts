import { describe, expect, it } from 'vitest'
import { createReadingBoundariesApi } from '../services/api-reading-boundaries'
import {
  createRequestRecorder,
  requestedThreadIds,
} from './requestRecorder'

describe('reading boundaries API', () => {
  it('uses the legacy authority for a mixed paginated batch without discarding responses', async () => {
    const { calls, client } = createRequestRecorder((call) => {
      const ids = requestedThreadIds(call)
      return {
        evaluator: ids.includes(201) ? 'enabled' : 'unavailable',
        threads: Object.fromEntries(ids.map((id) => [id, {
          thread_id: id,
          state: 'available',
          summary: 'Available now.',
          next: null,
          blockers: [],
        }])),
      }
    })

    const result = await createReadingBoundariesApi(client).batch(
      Array.from({ length: 201 }, (_, index) => index + 1),
    )

    expect(result.evaluator).toBe('unavailable')
    expect(Object.keys(result.threads)).toHaveLength(201)
    expect(calls.map(requestedThreadIds).map((ids) => ids.length)).toEqual([200, 1])
  })
})
