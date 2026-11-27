import { describe, expect, it } from 'vitest'
import { createThreadsApi } from '../services/api-threads'
import { createHttpClientStub } from './httpClientStub'

describe('threadsApi.create', () => {
  it('posts to the canonical v2 threads collection (#5702)', async () => {
    const client = createHttpClientStub()
    const payload = { title: 'Saga', format: 'Comic', issues_remaining: 4 }
    client.post.mockResolvedValueOnce({ ...payload, id: 7 })

    const api = createThreadsApi(client)
    await api.create(payload)

    expect(client.post).toHaveBeenCalledTimes(1)
    expect(client.post).toHaveBeenCalledWith('/v2/threads', payload)
  })
})

describe('threadsApi.checkExcludedStatus', () => {
  it('aggregates excluded and active ids across chunks', async () => {
    const client = createHttpClientStub()
    const ids = Array.from({ length: 1005 }, (_, index) => index + 1)
    client.post
      .mockResolvedValueOnce({
        excluded_thread_ids: [1, 2],
        active_thread_ids: [3, 4],
      })
      .mockResolvedValueOnce({
        excluded_thread_ids: [1005],
        active_thread_ids: [1004],
      })

    const api = createThreadsApi(client)
    const result = await api.checkExcludedStatus(ids)

    expect(client.post).toHaveBeenCalledTimes(2)
    expect(client.post).toHaveBeenNthCalledWith(1, '/v2/queue-exclusions/status:check', {
      thread_ids: ids.slice(0, 1000),
    })
    expect(client.post).toHaveBeenNthCalledWith(2, '/v2/queue-exclusions/status:check', {
      thread_ids: ids.slice(1000),
    })
    expect(result.excluded_thread_ids.sort((a, b) => a - b)).toEqual([1, 2, 1005])
    expect(result.active_thread_ids.sort((a, b) => a - b)).toEqual([3, 4, 1004])
  })

  it('treats missing active_thread_ids as empty', async () => {
    const client = createHttpClientStub()
    client.post.mockResolvedValueOnce({ excluded_thread_ids: [7] })

    const api = createThreadsApi(client)
    const result = await api.checkExcludedStatus([7, 8])

    expect(result).toEqual({ excluded_thread_ids: [7], active_thread_ids: [] })
  })
})

describe('threadsApi.checkPotentialDuplicates', () => {
  it('posts the advisory lookup to the v2 collection custom method', async () => {
    const client = createHttpClientStub()
    const request = {
      title: 'Amazing Spider-Man',
      format: 'Comic',
      comicvine_volume_id: 4050,
      exclude_thread_id: 12,
    }
    client.post.mockResolvedValueOnce({ matches: [] })

    const api = createThreadsApi(client)
    const result = await api.checkPotentialDuplicates(request)

    expect(client.post).toHaveBeenCalledWith('/v2/threads:checkDuplicates', request)
    expect(result).toEqual({ matches: [] })
  })

  it('sends only the fields the caller supplied', async () => {
    const client = createHttpClientStub()
    client.post.mockResolvedValueOnce({ matches: [] })

    const api = createThreadsApi(client)
    await api.checkPotentialDuplicates({ title: 'Saga', format: 'Comic' })

    expect(client.post).toHaveBeenCalledWith('/v2/threads:checkDuplicates', {
      title: 'Saga',
      format: 'Comic',
    })
  })
})
