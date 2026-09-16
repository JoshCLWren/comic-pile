import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useReaderContext } from '../hooks/useReaderContext'
import { readerContextApi } from '../services/api-reader-context'
import type { ReaderContextResponse } from '../types'

vi.mock('../services/api-reader-context', () => ({
  readerContextApi: { get: vi.fn() },
}))

const mockedGet = vi.mocked(readerContextApi.get)

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function context(issueId: number): ReaderContextResponse {
  return {
    issue_id: issueId,
    series: {
      identity_source: 'unavailable',
      canonical_series_id: null,
      series_name: null,
      average_rating: null,
      ratings_count: 0,
      previous_issue: null,
      recent_ratings: [],
      highest_rating: null,
      lowest_rating: null,
    },
    crossovers: [],
    local_chain: {
      issues: [{ issue_id, issue_number: '3', position: 1, status: 'unread', relation: 'current', rating: null, crossover_memberships: [] }],
      edges: [],
    },
  }
}

beforeEach(() => {
  mockedGet.mockReset()
})

it('never requests reader context while disabled or without an issue id', () => {
  const wrapper = createWrapper()
  const disabled = renderHook(() => useReaderContext(7, false), { wrapper })
  expect(disabled.result.current).toEqual({ context: null, isLoading: false, error: null, refetch: expect.any(Function) })
  const withoutIssue = renderHook(() => useReaderContext(null), { wrapper })
  expect(withoutIssue.result.current).toEqual({ context: null, isLoading: false, error: null, refetch: expect.any(Function) })
  expect(mockedGet).not.toHaveBeenCalled()
})

it('requests and returns the reader context for an enabled issue id', async () => {
  const wrapper = createWrapper()
  mockedGet.mockResolvedValue(context(7))
  const { result } = renderHook(() => useReaderContext(7), { wrapper })
  await waitFor(() => expect(result.current.context?.issue_id).toBe(7))
  expect(mockedGet).toHaveBeenCalledWith(7)
})

it('enables a query when it flips from disabled to enabled and returns the empty state when flipped back', async () => {
  const wrapper = createWrapper()
  mockedGet.mockResolvedValue(context(7))
  const { result, rerender } = renderHook(
    ({ issueId, enabled }: { issueId: number | null; enabled: boolean }) => useReaderContext(issueId, enabled),
    { wrapper, initialProps: { issueId: 7, enabled: false } },
  )
  expect(mockedGet).not.toHaveBeenCalled()
  rerender({ issueId: 7, enabled: true })
  await waitFor(() => expect(result.current.context?.issue_id).toBe(7))
  rerender({ issueId: 7, enabled: false })
  expect(result.current).toEqual({ context: null, isLoading: false, error: null, refetch: expect.any(Function) })
})

it('exposes a refetch bound to the enabled query', async () => {
  const wrapper = createWrapper()
  mockedGet.mockResolvedValueOnce(context(7)).mockResolvedValueOnce(context(9))
  const { result } = renderHook(() => useReaderContext(7), { wrapper })
  await waitFor(() => expect(result.current.context?.issue_id).toBe(7))
  await act(async () => {
    result.current.refetch()
  })
  await waitFor(() => expect(result.current.context?.issue_id).toBe(9))
  expect(mockedGet).toHaveBeenCalledTimes(2)
})

it('normalizes non-Error failures and preserves Error failures', async () => {
  mockedGet.mockRejectedValueOnce('string failure')
  const stringWrapper = createWrapper()
  const stringResult = renderHook(() => useReaderContext(7), { wrapper: stringWrapper })
  await waitFor(() => expect(stringResult.current.error).toBeInstanceOf(Error))
  expect(stringResult.current.error?.message).toBe('Unable to load reader context')

  mockedGet.mockRejectedValueOnce(new Error('boom'))
  const errorWrapper = createWrapper()
  const errorResult = renderHook(() => useReaderContext(7), { wrapper: errorWrapper })
  await waitFor(() => expect(errorResult.current.error).toBeInstanceOf(Error))
  expect(errorResult.current.error?.message).toBe('boom')
})