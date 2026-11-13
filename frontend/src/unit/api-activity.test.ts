import { beforeEach, describe, expect, it } from 'vitest'

import { createActivityApi } from '../services/api-activity'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const activityApi = createActivityApi(client)

beforeEach(() => {
  client.get.mockReset()
})

describe('activityApi.list', () => {
  it('requests the first page with neither cursor nor forced size', async () => {
    client.get.mockResolvedValueOnce({ events: [], next_page_token: null })

    await expect(activityApi.list()).resolves.toEqual({ events: [], next_page_token: null })
    expect(client.get).toHaveBeenCalledWith('/v2/activity', { params: {} })
  })

  it('carries the server cursor forward without a size override', async () => {
    client.get.mockResolvedValueOnce({ events: [], next_page_token: null })

    await activityApi.list('1731000000000000:1050513')

    expect(client.get).toHaveBeenCalledWith('/v2/activity', {
      params: { page_token: '1731000000000000:1050513' },
    })
  })

  it('applies a page size when no cursor is available yet', async () => {
    client.get.mockResolvedValueOnce({ events: [], next_page_token: null })

    await activityApi.list(null, 25)

    expect(client.get).toHaveBeenCalledWith('/v2/activity', { params: { page_size: 25 } })
  })

  it('sends both cursor and page size together', async () => {
    client.get.mockResolvedValueOnce({ events: [], next_page_token: null })

    await activityApi.list('1731000000000000:1050513', 25)

    expect(client.get).toHaveBeenCalledWith('/v2/activity', {
      params: { page_token: '1731000000000000:1050513', page_size: 25 },
    })
  })
})
