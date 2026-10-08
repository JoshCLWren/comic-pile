import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { createApiClient, getAccessToken, setAccessToken } from '../services/api'
import { createCreatorsApi } from '../services/api-creators'
import type { CreatorDetailResponse, CreatorListResponse } from '../services/api-creators'
import { createCreatorSummariesApi } from '../services/creatorsApi'
import type { CreatorSummariesResponse } from '../services/creatorsApi'
import { setDefaultHttpClient, type ApiRequestConfig } from '../services/httpClient'
import { createHttpClientStub } from './httpClientStub'
import { createTransportDouble } from './transportDouble'

/** Payload any of the three creator read services resolves to. */
type CreatorReadPayload = CreatorDetailResponse | CreatorListResponse | CreatorSummariesResponse

const client = createHttpClientStub()
const creatorsApi = createCreatorsApi(client)
const summariesApi = createCreatorSummariesApi(client)

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
    read_unrated_issues_complete: true,
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
  coverage: DETAIL_RESPONSE.coverage,
}

const SUMMARIES_RESPONSE = {
  summaries: [],
  requested_keys: ['creator:1672'],
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

  describe('getSummaries', () => {
    it('requests creator summaries with skipAuthRedirect: true', async () => {
      client.get.mockResolvedValue(SUMMARIES_RESPONSE)

      await expect(
        summariesApi.getSummaries(['creator:1672']),
      ).resolves.toEqual(SUMMARIES_RESPONSE)

      expect(client.get).toHaveBeenCalledWith('/v1/creators/summaries', {
        params: { keys: 'creator:1672' },
        skipAuthRedirect: true,
      })
    })
  })
})

/** Shape of the error object the shared response interceptor receives from axios. */
type RecoveryError = {
  config: ApiRequestConfig
  response: { status: number }
}

/** Registered response-error interceptor under test. */
type RecoveryInterceptor = (
  error: RecoveryError,
) => Promise<Record<string, string | number | boolean | null>>

/** URL assignments the shared `redirectToLogin` helper performs. */
const navigations: string[] = []
const realLocation = window.location

/**
 * Replace `window.location` so a login redirect is observable as data.
 *
 * jsdom performs no navigation, so asserting on `href` assignments is the only
 * way to prove the recoverable-transition fix keeps the user off `/login`.
 */
function stubLocation(): void {
  navigations.length = 0
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: {
      pathname: '/creators/creator%3A1672',
      get href() {
        return '/creators/creator%3A1672'
      },
      set href(value: string) {
        navigations.push(value)
      },
    },
  })
}

describe('creator reads during recoverable auth revalidation (issue #3212)', () => {
  let transport: ReturnType<typeof createTransportDouble>
  let recoveryApi: ReturnType<typeof createCreatorsApi>
  let recoveryInterceptor: RecoveryInterceptor

  beforeEach(() => {
    stubLocation()

    transport = createTransportDouble()
    const recoveryClient = createApiClient(() => transport)
    setDefaultHttpClient(recoveryClient)
    recoveryApi = createCreatorsApi(recoveryClient)
    setAccessToken('stale-access-token')

    // SAFETY: transport.interceptors.response.use is a vi.fn(); the second callback of its
    // first call is the registered error interceptor with the signature asserted here.
    recoveryInterceptor = transport.interceptors.response.use.mock.calls[0][1] as RecoveryInterceptor
  })

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      writable: true,
      value: realLocation,
    })
  })

  /**
   * Issue one creator read and return the exact config the real service emitted.
   *
   * Feeding this config to the shared interceptor is what makes the regression
   * test meaningful: it proves the service contract, not a hand-built config,
   * keeps a recoverable 401 off the login redirect.
   */
  function emittedConfig(issue: () => Promise<CreatorReadPayload>): ApiRequestConfig {
    void issue()
    // SAFETY: the stub records the (url, config) pair the service passed to get().
    const [url, config] = transport.get.mock.calls[0] as [string, ApiRequestConfig]
    return { ...config, url }
  }

  function unauthorizedRefresh(): Error & { response: { status: number } } {
    return Object.assign(new Error('refresh unauthorized'), { response: { status: 401 } })
  }

  it('recovers a creator detail read after refresh succeeds, never showing login', async () => {
    transport.post.mockResolvedValue({ access_token: 'refreshed-token' })
    transport.request.mockResolvedValue(DETAIL_RESPONSE)

    const detailConfig = emittedConfig(() => recoveryApi.getDetail('creator:1672'))

    await expect(
      recoveryInterceptor({ config: detailConfig, response: { status: 401 } }),
    ).resolves.toEqual(DETAIL_RESPONSE)

    expect(navigations).toEqual([])
    expect(getAccessToken()).toBe('refreshed-token')
    expect(transport.post).toHaveBeenCalledWith('/v1/auth/refresh', undefined, {
      skipAuthRedirect: true,
    })
    expect(transport.request).toHaveBeenCalledWith(expect.objectContaining({
      url: '/v1/creators/creator%3A1672',
      _retry: true,
      headers: expect.objectContaining({ Authorization: 'Bearer refreshed-token' }),
    }))
  })

  it('recovers a creator list read after refresh succeeds, never showing login', async () => {
    transport.post.mockResolvedValue({ access_token: 'refreshed-token' })
    transport.request.mockResolvedValue(LIST_RESPONSE)

    const listConfig = emittedConfig(() => recoveryApi.getList({ search: 'test' }))

    await expect(
      recoveryInterceptor({ config: listConfig, response: { status: 401 } }),
    ).resolves.toEqual(LIST_RESPONSE)

    expect(navigations).toEqual([])
    expect(transport.request).toHaveBeenCalledWith(expect.objectContaining({
      url: '/v1/creators',
      _retry: true,
    }))
  })

  it('recovers a creator summaries read after refresh succeeds, never showing login', async () => {
    const summariesRecoveryApi = createCreatorSummariesApi(
      createApiClient(() => transport),
    )
    transport.post.mockResolvedValue({ access_token: 'refreshed-token' })
    transport.request.mockResolvedValue(SUMMARIES_RESPONSE)

    const summariesConfig = emittedConfig(() => summariesRecoveryApi.getSummaries(['creator:1672']))

    await expect(
      recoveryInterceptor({ config: summariesConfig, response: { status: 401 } }),
    ).resolves.toEqual(SUMMARIES_RESPONSE)

    expect(navigations).toEqual([])
    expect(transport.request).toHaveBeenCalledWith(expect.objectContaining({
      url: '/v1/creators/summaries',
      _retry: true,
    }))
  })

  it('fails a creator detail read once, without redirect or recovery loop, when refresh is rejected', async () => {
    const refreshError = unauthorizedRefresh()
    transport.post.mockRejectedValueOnce(refreshError)

    const detailConfig = emittedConfig(() => recoveryApi.getDetail('creator:1672'))

    await expect(
      recoveryInterceptor({ config: detailConfig, response: { status: 401 } }),
    ).rejects.toBe(refreshError)

    expect(transport.post).toHaveBeenCalledTimes(1)
    expect(transport.request).not.toHaveBeenCalled()
    expect(navigations).toEqual([])
    expect(getAccessToken()).toBeNull()
  })

  it('fails a creator list read once, without redirect or recovery loop, when refresh is rejected', async () => {
    const refreshError = unauthorizedRefresh()
    transport.post.mockRejectedValueOnce(refreshError)

    const listConfig = emittedConfig(() => recoveryApi.getList())

    await expect(
      recoveryInterceptor({ config: listConfig, response: { status: 401 } }),
    ).rejects.toBe(refreshError)

    expect(transport.post).toHaveBeenCalledTimes(1)
    expect(transport.request).not.toHaveBeenCalled()
    expect(navigations).toEqual([])
  })

  it('confirms the redirect assertions have teeth by omitting the recovery config', async () => {
    const refreshError = unauthorizedRefresh()
    transport.post.mockRejectedValueOnce(refreshError)

    await expect(
      recoveryInterceptor({
        config: { url: '/v1/creators/creator%3A1672', headers: {} },
        response: { status: 401 },
      }),
    ).rejects.toBe(refreshError)

    expect(navigations).toEqual(['/login'])
  })
})
