import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { useSessionDetails, useSessionSnapshots } from '../hooks/useSession'
import { sessionApi } from '../services/api-sessions'
import { ToastProvider } from '../contexts/ToastProvider'

vi.mock('../services/api-sessions', () => ({
  sessionApi: {
    getDetails: vi.fn(),
    getSnapshots: vi.fn(),
  },
}))

const mockedSessionApi = vi.mocked(sessionApi)

function renderWithProvider<T>(hook: () => T): { result: { current: T } } {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return renderHook(hook, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <ToastProvider>{children}</ToastProvider>
      </QueryClientProvider>
    ),
  })
}

beforeEach(() => {
  // SAFETY: mock payload supplies only the fields this test asserts
  mockedSessionApi.getDetails.mockResolvedValue({ session_id: 3 } as never)
  // SAFETY: mock payload supplies only the fields this test asserts
  mockedSessionApi.getSnapshots.mockResolvedValue({ snapshots: [] } as never)
})

it('loads session details and snapshots', async () => {
  const { result: detailsResult } = renderWithProvider(() => useSessionDetails(3))
  const { result: snapshotsResult } = renderWithProvider(() => useSessionSnapshots(3))

  await waitFor(() => expect(detailsResult.current.data).toEqual({ session_id: 3 }))
  await waitFor(() => expect(snapshotsResult.current.data).toEqual({ snapshots: [] }))
  expect(mockedSessionApi.getDetails).toHaveBeenCalledWith(3)
  expect(mockedSessionApi.getSnapshots).toHaveBeenCalledWith(3)
})

it('handles empty ids and non-Error failures', async () => {
  const emptyDetails = renderWithProvider(() => useSessionDetails(null))
  const emptySnapshots = renderWithProvider(() => useSessionSnapshots(undefined))
  expect(emptyDetails.result.current.isPending).toBe(false)
  expect(emptySnapshots.result.current.isPending).toBe(false)

  mockedSessionApi.getDetails.mockRejectedValueOnce('details failed')
  const details = renderWithProvider(() => useSessionDetails(8))
  await waitFor(() => expect(details.result.current.error?.message).toBe('Failed to fetch session details'))
  mockedSessionApi.getSnapshots.mockRejectedValueOnce('snapshots failed')
  const snapshots = renderWithProvider(() => useSessionSnapshots(8))
  await waitFor(() => expect(snapshots.result.current.error?.message).toBe('Failed to fetch session snapshots'))
})

it('preserves Error instances from detail and snapshot requests', async () => {
  mockedSessionApi.getDetails.mockRejectedValueOnce(new Error('detail unavailable'))
  mockedSessionApi.getSnapshots.mockRejectedValueOnce(new Error('snapshot unavailable'))
  const details = renderWithProvider(() => useSessionDetails(12))
  const snapshots = renderWithProvider(() => useSessionSnapshots(12))
  await waitFor(() => expect(details.result.current.error?.message).toBe('detail unavailable'))
  await waitFor(() => expect(snapshots.result.current.error?.message).toBe('snapshot unavailable'))
})
