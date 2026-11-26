import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  useComicVineMetadataHydration,
  type UseComicVineMetadataHydrationArgs,
} from '../hooks/useComicVineMetadataHydration'
import {
  comicVineApi,
  type ComicVineIssueIntelligence,
  type MetadataRefreshResponse,
} from '../services/api-comicvine'

vi.mock('../services/api-comicvine', async () => {
  const actual = await vi.importActual<typeof import('../services/api-comicvine')>(
    '../services/api-comicvine',
  )
  return { ...actual, comicVineApi: { refreshMetadata: vi.fn() } }
})

const refreshMetadata = vi.mocked(comicVineApi.refreshMetadata)

function metadata(overrides: Partial<ComicVineIssueIntelligence> = {}): ComicVineIssueIntelligence {
  return {
    comicvine_issue_id: '100',
    comicvine_url: null,
    series_name: 'Test Series',
    series_id: 1,
    issue_number: '1',
    name: 'Test Issue',
    description: null,
    image_url: null,
    cover_date: null,
    store_date: null,
    creators: [],
    story_arcs: [],
    ...overrides,
  }
}

function apiError(status: number, headers: object = {}) {
  return Object.assign(new Error(`HTTP ${status}`), {
    response: { status, data: { detail: `HTTP ${status}` }, headers },
  })
}

function refreshed(overrides: Partial<MetadataRefreshResponse> = {}): MetadataRefreshResponse {
  return { issue_id: 1, refreshed: true, comicvine_issue_id: '100', ...overrides }
}

function renderHydration(overrides: Partial<UseComicVineMetadataHydrationArgs> = {}) {
  const args: UseComicVineMetadataHydrationArgs = {
    issueId: 1,
    metadata: metadata({ metadata_status: 'not_deep_fetched' }),
    isLoading: false,
    isError: false,
    refetch: vi.fn().mockResolvedValue(metadata()),
    ...overrides,
  }
  return { args, ...renderHook(() => useComicVineMetadataHydration(args)) }
}

beforeEach(() => {
  refreshMetadata.mockReset()
  refreshMetadata.mockResolvedValue(refreshed())
})

describe('useComicVineMetadataHydration boundary decoding', () => {
  it('reports truthful loading/idle states without an issue or intelligence', () => {
    const loading = renderHydration({ issueId: null, metadata: null, isLoading: true })
    expect(loading.result.current.state).toBe('loading')
    expect(loading.result.current.showRetry).toBe(false)
    expect(loading.result.current.canRetry).toBe(false)

    loading.rerender()
    loading.result.current.isLoading === false
    expect(loading.result.current.state).toBeNull()
    expect(refreshMetadata).not.toHaveBeenCalled()
  })

  it('offers Retry but never auto-hydrates when autoHydrate is false', () => {
    const { result } = renderHydration({ autoHydrate: false })
    expect(result.current.state).toBe('not-hydrated')
    expect(result.current.showRetry).toBe(true)
    expect(result.current.canRetry).toBe(true)
    expect(refreshMetadata).not.toHaveBeenCalled()
  })

  it('does not auto-hydrate on a canonical error, missing intelligence, or present credits', () => {
    const errored = renderHydration({ issueId: 2, isError: true })
    expect(errored.result.current.state).toBe('not-hydrated')
    expect(refreshMetadata).not.toHaveBeenCalled()

    const missing = renderHydration({ issueId: 3, metadata: null })
    expect(missing.result.current.state).toBeNull()

    const credited = renderHydration({
      issueId: 4,
      metadata: metadata({ metadata_status: 'complete', creators: [{ name: 'Writer', roles: ['writer'] }] }),
    })
    expect(credited.result.current.state).toBe('credits')
    expect(credited.result.current.showRetry).toBe(false)
    expect(refreshMetadata).not.toHaveBeenCalled()
  })

  it('sets a cooldown from a positive response retry_after_seconds', async () => {
    refreshMetadata.mockResolvedValue(refreshed({ retry_after_seconds: 2 }))
    const { result } = renderHydration({ issueId: 5 })

    await waitFor(() => expect(refreshMetadata).toHaveBeenCalledTimes(1))
    expect(result.current.retryAfterSeconds).toBeGreaterThan(0)
    expect(result.current.canRetry).toBe(false)
    expect(result.current.isHydrating).toBe(false)
  })

  it('ignores zero, negative and malformed response retry_after_seconds', async () => {
    for (const [index, retryAfter] of [0, -5, Number.NaN].entries()) {
      refreshMetadata.mockResolvedValueOnce(refreshed({ retry_after_seconds: retryAfter }))
      const { result } = renderHydration({ issueId: 10 + index })
      await waitFor(() => expect(refreshMetadata).toHaveBeenCalled())
      expect(result.current.retryAfterSeconds).toBe(0)
      expect(result.current.canRetry).toBe(true)
    }
  })

  it('honors a positive canonical refresh_retry_after_seconds and ignores malformed ones', async () => {
    const delayed = renderHydration({
      issueId: 20,
      metadata: metadata({ metadata_status: 'refresh_deferred', refresh_retry_after_seconds: 1 }),
    })
    await waitFor(() => expect(delayed.result.current.retryAfterSeconds).toBeGreaterThan(0))
    expect(delayed.result.current.canRetry).toBe(false)
    expect(refreshMetadata).not.toHaveBeenCalled()

    for (const [index, seconds] of [0, -1].entries()) {
      const ignored = renderHydration({
        issueId: 21 + index,
        metadata: metadata({ metadata_status: 'refresh_deferred', refresh_retry_after_seconds: seconds }),
      })
      expect(ignored.result.current.retryAfterSeconds).toBe(0)
      expect(ignored.result.current.canRetry).toBe(true)
    }
  })

  it('decodes a string Retry-After header but falls back for malformed headers', async () => {
    refreshMetadata.mockRejectedValue(apiError(429, { 'retry-after': '3' }))
    const withHeader = renderHydration({
      issueId: 30,
      metadata: metadata({ metadata_status: 'refresh_failed' }),
      autoHydrate: false,
    })
    await act(async () => {
      await withHeader.result.current.retry()
    })
    expect(withHeader.result.current.state).toBe('rate-limited')
    expect(withHeader.result.current.retryAfterSeconds).toBeGreaterThan(0)

    // SAFETY: the test intentionally supplies a hostile non-string header value.
    refreshMetadata.mockRejectedValueOnce(apiError(429, { 'retry-after': 3 } as object))
    const nonString = renderHydration({
      issueId: 31,
      metadata: metadata({ metadata_status: 'refresh_failed' }),
      autoHydrate: false,
    })
    await act(async () => {
      await nonString.result.current.retry()
    })
    expect(nonString.result.current.state).toBe('rate-limited')
    expect(nonString.result.current.retryAfterSeconds).toBeGreaterThan(0)

    refreshMetadata.mockRejectedValueOnce(apiError(429))
    const noHeader = renderHydration({
      issueId: 32,
      metadata: metadata({ metadata_status: 'refresh_failed' }),
      autoHydrate: false,
    })
    await act(async () => {
      await noHeader.result.current.retry()
    })
    expect(noHeader.result.current.retryAfterSeconds).toBeGreaterThan(0)

    refreshMetadata.mockRejectedValueOnce('offline')
    const notAnObject = renderHydration({
      issueId: 33,
      metadata: metadata({ metadata_status: 'refresh_failed' }),
      autoHydrate: false,
    })
    await act(async () => {
      await notAnObject.result.current.retry()
    })
    expect(notAnObject.result.current.state).toBe('unavailable')
  })

  it('classifies explicit negative hydration outcomes distinctly', async () => {
    const cases = [
      ['unavailable', 'unavailable'],
      ['rate_limited', 'rate-limited'],
      ['timeout', 'timeout'],
      ['invalid_response', 'invalid-response'],
      ['refresh_failed', 'failed'],
    ] as const
    for (const [index, [outcome, expected]] of cases.entries()) {
      refreshMetadata.mockResolvedValueOnce(refreshed({ outcome }))
      const { result } = renderHydration({
        issueId: 40 + index,
        autoHydrate: false,
        metadata: metadata({ metadata_status: 'not_deep_fetched' }),
      })
      await act(async () => {
        await result.current.retry()
      })
      expect(result.current.state).toBe(expected)
    }
  })

  it('never lets a late response from a remapped identity update the new one', async () => {
    let resolveRefresh: ((value: MetadataRefreshResponse) => void) | undefined
    refreshMetadata.mockImplementation(() => new Promise((resolve) => {
      resolveRefresh = resolve
    }))
    const refetch = vi.fn().mockResolvedValue(metadata())
    const { result, rerender } = renderHydration({ issueId: 50, refetch })
    await waitFor(() => expect(refreshMetadata).toHaveBeenCalledTimes(1))
    const beforeRemap = refetch.mock.calls.length

    rerender()
    const remapped = metadata({ comicvine_issue_id: '999', metadata_status: 'not_deep_fetched' })
    result.current // keep the hook mounted before the identity change
    const next = renderHook(() => useComicVineMetadataHydration({
      issueId: 51,
      metadata: remapped,
      isLoading: false,
      isError: false,
      refetch,
      autoHydrate: false,
    }))
    await act(async () => {
      resolveRefresh?.(refreshed({ outcome: 'unavailable' }))
    })
    expect(refetch).toHaveBeenCalledTimes(beforeRemap)
    expect(next.result.current.state).toBe('not-hydrated')
  })

  it('deduplicates concurrent Retry calls for the same identity', async () => {
    let resolveRefresh: ((value: MetadataRefreshResponse) => void) | undefined
    refreshMetadata.mockImplementation(() => new Promise((resolve) => {
      resolveRefresh = resolve
    }))
    const { result } = renderHydration({
      issueId: 60,
      metadata: metadata({ metadata_status: 'refresh_failed' }),
      autoHydrate: false,
    })

    await act(async () => {
      const first = result.current.retry()
      const second = result.current.retry()
      await Promise.resolve()
      resolveRefresh?.(refreshed())
      await Promise.all([first, second])
    })
    expect(refreshMetadata).toHaveBeenCalledTimes(1)
  })
})
