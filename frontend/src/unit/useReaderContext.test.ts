import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useReaderContext } from '../hooks/useReaderContext'
import { readerContextApi } from '../services/api'

vi.mock('../services/api', () => ({
  readerContextApi: { get: vi.fn() },
}))

const mockedApi = vi.mocked(readerContextApi)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useReaderContext', () => {
  it('loads data for a given issue ID', async () => {
    const mockData = {
      canonical_series: {
        identity_source: 'external_identity',
        average_rating: 4.25,
        rated_count: 3,
        previous_issue: null,
        recent_ratings: [],
        highest_rating: 4.5,
        lowest_rating: 4.0,
      },
      crossover_panel: [],
    }
    mockedApi.get.mockResolvedValue(mockData)

    const { result } = renderHook(() => useReaderContext(42))

    expect(result.current.isLoading).toBe(true)
    await waitFor(() => expect(result.current.data).toEqual(mockData))
    expect(result.current.isLoading).toBe(false)
    expect(result.current.error).toBeNull()
    expect(mockedApi.get).toHaveBeenCalledWith(42)
  })

  it('returns empty state when issueId is null', () => {
    const { result } = renderHook(() => useReaderContext(null))

    expect(result.current.data).toBeNull()
    expect(result.current.isLoading).toBe(false)
    expect(result.current.error).toBeNull()
    expect(mockedApi.get).not.toHaveBeenCalled()
  })

  it('returns empty state when issueId is undefined', () => {
    const { result } = renderHook(() => useReaderContext(undefined))

    expect(result.current.data).toBeNull()
    expect(result.current.isLoading).toBe(false)
    expect(result.current.error).toBeNull()
    expect(mockedApi.get).not.toHaveBeenCalled()
  })

  it('handles API errors', async () => {
    mockedApi.get.mockRejectedValue(new Error('Network error'))

    const { result } = renderHook(() => useReaderContext(42))

    await waitFor(() => expect(result.current.error?.message).toBe('Network error'))
    expect(result.current.isLoading).toBe(false)
    expect(result.current.data).toBeNull()
  })

  it('handles non-Error rejections', async () => {
    mockedApi.get.mockRejectedValue('string error')

    const { result } = renderHook(() => useReaderContext(42))

    await waitFor(() => expect(result.current.error?.message).toBe('Unable to load reader context'))
    expect(result.current.isLoading).toBe(false)
  })

  it('ignores stale responses after issueId changes', async () => {
    let resolveFirst: ((value: unknown) => void) | undefined
    mockedApi.get
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce({
        canonical_series: { identity_source: 'external_identity', average_rating: 3.0, rated_count: 1, previous_issue: null, recent_ratings: [], highest_rating: 3.0, lowest_rating: 3.0 },
        crossover_panel: [],
      })

    const { result, rerender } = renderHook(
      ({ id }) => useReaderContext(id),
      { initialProps: { id: 42 as number | null } },
    )

    rerender({ id: 99 })

    await waitFor(() => expect(result.current.data).not.toBeNull())

    resolveFirst?.({
      canonical_series: { identity_source: 'external_identity', average_rating: 5.0, rated_count: 1, previous_issue: null, recent_ratings: [], highest_rating: 5.0, lowest_rating: 5.0 },
      crossover_panel: [],
    })

    // The stale response for issue 42 should not overwrite issue 99's data
    expect(result.current.data?.canonical_series?.average_rating).not.toBe(5.0)
  })

  it('provides a refetch function that re-fetches data', async () => {
    mockedApi.get
      .mockResolvedValueOnce({
        canonical_series: null,
        crossover_panel: [],
      })
      .mockResolvedValueOnce({
        canonical_series: { identity_source: 'external_identity', average_rating: 4.0, rated_count: 2, previous_issue: null, recent_ratings: [], highest_rating: 4.0, lowest_rating: 4.0 },
        crossover_panel: [],
      })

    const { result } = renderHook(() => useReaderContext(42))

    await waitFor(() => expect(result.current.data).not.toBeNull())
    expect(result.current.data?.canonical_series).toBeNull()

    result.current.refetch()

    await waitFor(() => expect(result.current.data?.canonical_series).not.toBeNull())
    expect(mockedApi.get).toHaveBeenCalledTimes(2)
  })
})
