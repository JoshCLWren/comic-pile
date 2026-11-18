import { describe, expect, it } from 'vitest'

import type { ListActivityResponse } from '../generated/nativeV2Client'
import { ACTIVITY_PAGE_SIZE, createActivityApi, type ActivityItem } from '../services/api-activity'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const activityApi = createActivityApi(client)

const item: ActivityItem = {
  event_id: 1050512,
  type: 'snooze',
  timestamp: '2026-11-08T15:46:25.515000Z',
  die_before: 6,
  die_after: 8,
  rating: null,
  issue_id: null,
  thread_id: 3153,
  thread_title: 'Saga',
  issue_number: null,
}

function response(overrides: Partial<ListActivityResponse> = {}): ListActivityResponse {
  return {
    activities: [item],
    events: [item],
    items: [item],
    next_page_token: 'page-2',
    next_cursor: 'page-2',
    ...overrides,
  }
}

describe('activityApi', () => {
  it('reads the first page from the native owner-scoped activity resource', async () => {
    client.get.mockResolvedValue(response())

    await expect(activityApi.list()).resolves.toEqual({
      items: [item],
      next_page_token: 'page-2',
    })
    expect(client.get).toHaveBeenCalledWith('/v2/activity', {
      params: { limit: ACTIVITY_PAGE_SIZE },
    })
  })

  it('forwards the opaque continuation token instead of a client-built cursor', async () => {
    client.get.mockResolvedValue(response({ next_page_token: null, next_cursor: null }))

    await expect(activityApi.list('page-2')).resolves.toEqual({
      items: [item],
      next_page_token: null,
    })
    expect(client.get).toHaveBeenCalledWith('/v2/activity', {
      params: { limit: ACTIVITY_PAGE_SIZE, page_token: 'page-2' },
    })
  })

  it('normalizes an absent continuation token to null', async () => {
    client.get.mockResolvedValue(response({ next_page_token: undefined, next_cursor: undefined }))

    await expect(activityApi.list()).resolves.toEqual({
      items: [item],
      next_page_token: null,
    })
  })
})
