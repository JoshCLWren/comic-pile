import { beforeEach, describe, expect, it, vi } from 'vitest'

const { get } = vi.hoisted(() => ({ get: vi.fn() }))

vi.mock('../services/api', () => ({
  default: { get },
}))

import { releasesApi } from '../services/api-releases'

beforeEach(() => {
  get.mockReset()
})

describe('releasesApi', () => {
  it('uses the public release-list defaults', async () => {
    const payload = { releases: [], next_page_token: null }
    get.mockResolvedValue(payload)

    await expect(releasesApi.list()).resolves.toEqual(payload)
    expect(get).toHaveBeenCalledWith('/v1/releases/', {
      params: {},
    })
  })

  it('passes incremental pagination through to the release API', async () => {
    const payload = { releases: [], total: 75, limit: 50, offset: 20 }
    get.mockResolvedValue(payload)

    await expect(releasesApi.list(50, 'token-123')).resolves.toEqual(payload)
    expect(get).toHaveBeenCalledWith('/v1/releases/', {
      params: {
        page_size: 50,
        page_token: 'token-123',
      },
    })
  })
})
