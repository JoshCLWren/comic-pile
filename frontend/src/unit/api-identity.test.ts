import { beforeEach, describe, expect, it, vi } from 'vitest'

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))

// The service binds the shared client at import time, so the transport is
// doubled here instead of standing up the real axios/interceptor pipeline.
vi.mock('../services/api', () => ({
  default: {
    get,
    post,
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    head: vi.fn(),
  },
}))

import { identityInboxApi } from '../services/api-identity'

describe('identityInboxApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    get.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 20 })
    post.mockResolvedValue(undefined)
  })

  it('lists inbox items with pagination parameters', async () => {
    await identityInboxApi.list(20, 10)

    expect(get).toHaveBeenCalledWith('/v2/identity-inbox', {
      params: { offset: 20, limit: 10 },
    })
  })

  it('#5434 searches provider matches with an issue scope and bounded limit', async () => {
    const response = {
      issue_id: 10,
      query: 'B.P.R.D.',
      results: [],
      total_available: 0,
      partial_matches: [],
      no_match_reason: null,
    }
    get.mockResolvedValue(response)

    await expect(identityInboxApi.searchMatches('B.P.R.D.', 10)).resolves.toBe(response)
    expect(get).toHaveBeenCalledWith('/v2/identity-inbox/issue-matches', {
      params: { q: 'B.P.R.D.', issue_id: 10, limit: 20 },
    })
  })

  it('confirms, rejects, defers and skips through the existing scoped routes', async () => {
    await identityInboxApi.confirm(1, { external_identity_id: 501 })
    await identityInboxApi.reject(2, {
      external_identity_id: 502,
      rejection_reason: 'wrong volume',
    })
    await identityInboxApi.defer(3)
    await identityInboxApi.skip(4)

    expect(post).toHaveBeenNthCalledWith(
      1,
      '/v2/identity-inbox/1/confirmations',
      { external_identity_id: 501 },
    )
    expect(post).toHaveBeenNthCalledWith(
      2,
      '/v2/identity-inbox/2/rejections',
      { external_identity_id: 502, rejection_reason: 'wrong volume' },
    )
    expect(post).toHaveBeenNthCalledWith(3, '/v2/identity-inbox/3/deferrals')
    expect(post).toHaveBeenNthCalledWith(4, '/v2/identity-inbox/4/skips')
  })
})
