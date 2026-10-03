import { describe, expect, it } from 'vitest'

import { createDemoApi } from '../services/api-demo'
import type { RollResponse } from '../types'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const demoApi = createDemoApi(client)

describe('demoApi', () => {
  it('reads the seeded roll from the canonical versioned demo path', async () => {
    const payload: RollResponse = {
      thread_id: 999,
      title: 'Sample: The Dark Knight Returns (Demo)',
      format: 'comic',
      issues_remaining: 3,
      queue_position: 1,
      die_size: 6,
      result: 4,
      offset: 0,
      snoozed_count: 0,
      issue_id: 1001,
      issue_number: '#4',
      next_issue_id: 1002,
      next_issue_number: '#5',
      total_issues: 12,
      reading_progress: null,
      explanation: 'Demo roll: seeded sample data, no account state.',
    }
    client.get.mockResolvedValue(payload)

    await expect(demoApi.roll()).resolves.toEqual(payload)
    expect(client.get).toHaveBeenCalledWith('/v1/demo/roll')
  })

  it('exposes no write method so demo interactions cannot persist', () => {
    expect(Object.keys(demoApi)).toEqual(['roll'])
  })
})
