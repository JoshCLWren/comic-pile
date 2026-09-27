import { describe, expect, it } from 'vitest'

import { createReleasesApi } from '../services/api-releases'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const releasesApi = createReleasesApi(client)

describe('releasesApi', () => {
  it('uses the public release-list defaults', async () => {
    const payload = { releases: [], total: 0, limit: 20, offset: 0 }
    client.get.mockResolvedValue(payload)

    await expect(releasesApi.list()).resolves.toEqual(payload)
    expect(client.get).toHaveBeenCalledWith('/v1/releases/', {
      params: { limit: 20, offset: 0 },
    })
  })

  it('passes incremental pagination through to the release API', async () => {
    const payload = { releases: [], total: 75, limit: 50, offset: 20 }
    client.get.mockResolvedValue(payload)

    await expect(releasesApi.list(50, 20)).resolves.toEqual(payload)
    expect(client.get).toHaveBeenCalledWith('/v1/releases/', {
      params: { limit: 50, offset: 20 },
    })
  })
})
