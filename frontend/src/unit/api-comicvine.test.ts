import { beforeEach, describe, expect, it, vi } from 'vitest'

const { post, get } = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn() }))

// The service module binds the shared client at import time, so the transport is
// doubled here instead of standing up the real axios/interceptor pipeline.
vi.mock('../services/api', () => ({
  default: { post, get, put: vi.fn(), patch: vi.fn(), delete: vi.fn(), head: vi.fn() },
}))

import { COMICVINE_ROSTER_TIMEOUT_MS, SERIES_IMPORT_TIMEOUT_MS, comicVineApi } from '../services/api-comicvine'

describe('comicVineApi series import (#3445)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('gives the series import its own request budget instead of the shared default', async () => {
    post.mockResolvedValue({ thread_id: 501 })

    await comicVineApi.importSeries({ comicvine_volume_id: 42, already_read_count: 0 })

    expect(post).toHaveBeenCalledWith(
      '/v2/comicvine/series:import',
      { comicvine_volume_id: 42, already_read_count: 0 },
      { timeout: SERIES_IMPORT_TIMEOUT_MS },
    )
    // A series import adopts every provider issue for one volume, so the shared
    // 10s default expired while the server kept importing and committed anyway,
    // which the client reported as "Network error" on a successful import.
    expect(SERIES_IMPORT_TIMEOUT_MS).toBeGreaterThan(10_000)
  })

  it('reads one volume committed import status from the server', async () => {
    get.mockResolvedValue({
      comicvine_volume_id: 42,
      imported: true,
      thread_id: 501,
      series_name: 'Stormwatch',
      issue_count: 12,
    })

    const status = await comicVineApi.getSeriesImportStatus(42)

    expect(get).toHaveBeenCalledWith('/v2/comicvine/series/42/import-status')
    expect(status.imported).toBe(true)
    expect(status.thread_id).toBe(501)
    expect(status.issue_count).toBe(12)
  })
})
describe('comicVineApi native v2 provider reads (#4835)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    get.mockResolvedValue({})
  })

  it('searches series on the v2 route with the shared default budget', async () => {
    await comicVineApi.searchSeries('Saga', 10, 20)

    expect(get).toHaveBeenCalledWith('/v2/comicvine/search/series', {
      params: { q: 'Saga', limit: 10, offset: 20 },
    })
  })

  it('gives the roster-backed resolve and series-issues reads a budget above the 50s server deadline', async () => {
    await comicVineApi.resolveIdentity('https://comicvine.gamespot.com/saga/4050-9/')
    await comicVineApi.getSeriesIssues(9, 'Saga')

    expect(get).toHaveBeenCalledWith('/v2/comicvine/resolve', {
      params: { input: 'https://comicvine.gamespot.com/saga/4050-9/' },
      timeout: COMICVINE_ROSTER_TIMEOUT_MS,
    })
    expect(get).toHaveBeenCalledWith('/v2/comicvine/series/9/issues', {
      params: { series_name: 'Saga' },
      timeout: COMICVINE_ROSTER_TIMEOUT_MS,
    })
    expect(COMICVINE_ROSTER_TIMEOUT_MS).toBeGreaterThan(50_000)
  })
})
