import { beforeEach, describe, expect, it } from 'vitest'

import { createApiClient, setAccessToken } from '../services/api'
import { createCreatorsApi } from '../services/api-creators'
import { setDefaultHttpClient } from '../services/httpClient'
import { createHttpClientStub } from './httpClientStub'
import { createTransportDouble } from './transportDouble'

const client = createHttpClientStub()
const creatorsApi = createCreatorsApi(client)

const DETAIL_RESPONSE = {
  summary: {
    canonical_creator_key: 'creator:1672',
    display_name: 'Test Creator',
    normalized_roles: ['writer'],
    average_rating: 4.5,
    ratings_count: 10,
    read_unrated_count: 2,
    upcoming_count: 1,
  },
  coverage: {
    rated_issues_total: 10,
    rated_issues_with_creator_metadata: 10,
    ratings_complete: true,
    read_unrated_issues_total: 2,
    read_unrated_issues_with_metadata: 2,
    read_unrated_complete: true,
    unread_issues_total: 0,
    unread_issues_with_metadata: 0,
    upcoming_complete: true,
  },
  role_stats: [],
  rated_issues: [],
  read_unrated_issues: [],
  upcoming_issues: [],
  next_cursor: null,
  rating_distribution: null,
}

const LIST_RESPONSE = {
  items: [
    {
      canonical_creator_key: 'creator:1672',
      display_name: 'Test Creator',
      normalized_roles: ['writer'],
      average_rating: 4.5,
      ratings_count: 10,
    },
  ],
  total: 1,
  limit: 20,
  offset: 0,
  coverage: {
    rated_issues_total: 10,
    rated_issues_with_creator_metadata: 10,
    ratings_complete: true,
    read_unrated_issues_total: 2,
    read_unrated_issues_with_metadata: 2,
    read_unrated_complete: true,
    unread_issues_total: 0,
    unread_issues_with_metadata: 0,
    upcoming_complete: true,
  },
}

describe('creatorsApi', () => {
  describe('getDetail', () => {
    it('requests creator detail with skipAuthRedirect: true', async () => {
      client.get.mockResolvedValue(DETAIL_RESPONSE)

      await expect(
        creatorsApi.getDetail('creator:1672', { limit: 10 }),
      ).resolves.toEqual(DETAIL_RESPONSE)

      expect(client.get).toHaveBeenCalledWith('/v1/creators/creator%3A1672', {
        params: { limit: 10 },
        skipAuthRedirect: true,
      })
    })

    it('requests creator detail with only required params', async () => {
      client.get.mockResolvedValue(DETAIL_RESPONSE)

      await expect(
        creatorsApi.getDetail('creator:1672'),
      ).resolves.toEqual(DETAIL_RESPONSE)

      expect(client.get).toHaveBeenCalledWith('/v1/creators/creator%3A1672', {
        params: {},
        skipAuthRedirect: true,
      })
    })
  })

  describe('getList', () => {
    it('requests creator list with skipAuthRedirect: true', async () => {
      client.get.mockResolvedValue(LIST_RESPONSE)

      await expect(
        creatorsApi.getList({ search: 'test', sort: 'name', limit: 20 }),
      ).resolves.toEqual(LIST_RESPONSE)

      expect(client.get).toHaveBeenCalledWith('/v1/creators', {
        params: { search: 'test', sort: 'name', limit: 20 },
        skipAuthRedirect: true,
      })
    })

    it('requests creator list with search only', async () => {
      client.get.mockResolvedValue(LIST_RESPONSE)

      await expect(
        creatorsApi.getList({ search: 'test' }),
      ).resolves.toEqual(LIST_RESPONSE)

      expect(client.get).toHaveBeenCalledWith('/v1/creators', {
        params: { search: 'test' },
        skipAuthRedirect: true,
      })
    })

    it('requests creator list with no params', async () => {
      client.get.mockResolvedValue(LIST_RESPONSE)

      await expect(
        creatorsApi.getList(),
      ).resolves.toEqual(LIST_RESPONSE)

      expect(client.get).toHaveBeenCalledWith('/v1/creators', {
        params: {},
        skipAuthRedirect: true,
      })
    })
  })
})

describe('creatorsApi auth recovery', () => {
  let transport: ReturnType<typeof createTransportDouble>
  let recoveryApi: ReturnType<typeof createCreatorsApi>
  let responseInterceptor: (
    error: {
      config: { url: string; skipAuthRedirect?: boolean }
      response: { status: number }
    },
  ) => Promise<Record<string, string | number | boolean | null>>

  beforeEach(() => {
    transport = createTransportDouble()
    const recoveryClient = createApiClient(() => transport)
    setDefaultHttpClient(recoveryClient)
    recoveryApi = createCreatorsApi(recoveryClient)
    setAccessToken('stale-access-token')

    // SAFETY: transport.interceptors.response.use is a vi.fn(); the second callback of its
    // first call is the registered error interceptor with the signature asserted here.
    responseInterceptor = transport.interceptors.response.use.mock.calls[0][1] as (
      error: {
        config: { url: string; skipAuthRedirect?: boolean }
        response: { status: number }
      },
    ) => Promise<Record<string, string | number | boolean | null>>
  })

  it('retries creator detail after refresh succeeds', async () => {
    transport.post.mockResolvedValue({ access_token: 'refreshed-token' })
    transport.request.mockResolvedValue(DETAIL_RESPONSE)

    const originalRequest = {
      url: '/v1/creators/creator%3A1672',
      headers: {},
      skipAuthRedirect: true,
    }

    const result = await responseInterceptor({
      config: originalRequest,
      response: { status: 401 },
    })

    expect(result).toEqual(DETAIL_RESPONSE)
    expect(transport.post).toHaveBeenCalledWith(
      '/v1/auth/refresh',
      undefined,
      expect.objectContaining({ skipAuthRedirect: true }),
    )
    expect(transport.request).toHaveBeenCalledWith(
      expect.objectContaining({
        url: '/v1/creators/creator%3A1672',
        _retry: true,
        headers: expect.objectContaining({ Authorization: 'Bearer refreshed-token' }),
      }),
    )
  })

  it('retries creator list after refresh succeeds', async () => {
    transport.post.mockResolvedValue({ access_token: 'refreshed-token' })
    transport.request.mockResolvedValue(LIST_RESPONSE)

    const originalRequest = {
      url: '/v1/creators',
      headers: {},
      skipAuthRedirect: true,
    }

    const result = await responseInterceptor({
      config: originalRequest,
      response: { status: 401 },
    })

    expect(result).toEqual(LIST_RESPONSE)
    expect(transport.post).toHaveBeenCalledWith(
      '/v1/auth/refresh',
      undefined,
      expect.objectContaining({ skipAuthRedirect: true }),
    )
  })

  it('rejects creator detail when refresh fails definitively without redirecting', async () => {
    const refreshError = Object.assign(new Error('refresh unauthorized'), {
      response: { status: 401 },
    })
    transport.post.mockRejectedValueOnce(refreshError)

    await expect(
      responseInterceptor({
        config: {
          url: '/v1/creators/creator%3A1672',
          skipAuthRedirect: true,
        },
        response: { status: 401 },
      }),
    ).rejects.toBe(refreshError)

    expect(transport.post).toHaveBeenCalledTimes(1)
  })

  it('rejects creator list when refresh fails definitively without redirecting', async () => {
    const refreshError = Object.assign(new Error('refresh unauthorized'), {
      response: { status: 401 },
    })
    transport.post.mockRejectedValueOnce(refreshError)

    await expect(
      responseInterceptor({
        config: {
          url: '/v1/creators',
          skipAuthRedirect: true,
        },
        response: { status: 401 },
      }),
    ).rejects.toBe(refreshError)

    expect(transport.post).toHaveBeenCalledTimes(1)
  })
})
