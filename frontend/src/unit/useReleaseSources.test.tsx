import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useReleaseSources, useEnableReleaseSource } from '../hooks/useReleaseSources'

const mocks = vi.hoisted(() => ({
  listReleaseSources: vi.fn(),
  updateReleaseSourceEnabled: vi.fn(),
}))

vi.mock('../services/api-continuity-plans', async () => {
  const actual = await vi.importActual<typeof import('../services/api-continuity-plans')>(
    '../services/api-continuity-plans',
  )
  return {
    ...actual,
    continuityPlansApi: {
      ...actual.continuityPlansApi,
      listReleaseSources: mocks.listReleaseSources,
      updateReleaseSourceEnabled: mocks.updateReleaseSourceEnabled,
    },
  }
})

const mockList = mocks.listReleaseSources
const mockUpdate = mocks.updateReleaseSourceEnabled

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const sampleSources = [
  {
    source_id: 901,
    thread_id: 4,
    external_identity_id: 77,
    provider_volume_id: '4000-77',
    provider_title: 'X-Men',
    provider_publisher: 'Marvel',
    provider_start_year: 1963,
    provider_issue_count: 12,
    enabled: true,
    last_synced_at: '2026-10-17T05:00:00Z',
  },
  {
    source_id: 902,
    thread_id: 5,
    external_identity_id: 78,
    provider_volume_id: '4000-78',
    provider_title: 'Incredible Hulk',
    provider_publisher: 'Marvel',
    provider_start_year: 1962,
    provider_issue_count: 10,
    enabled: false,
    last_synced_at: null,
  },
]

describe('useReleaseSources', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockList.mockResolvedValue(sampleSources)
  })

  it('fetches release sources when planId is provided', async () => {
    const { result } = renderHook(() => useReleaseSources(12), { wrapper: createWrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mockList).toHaveBeenCalledWith(12)
    expect(result.current.data).toEqual(sampleSources)
  })

  it('does not fetch when planId is null', () => {
    const { result } = renderHook(() => useReleaseSources(null), { wrapper: createWrapper() })
    expect(result.current.data).toBeUndefined()
    expect(mockList).not.toHaveBeenCalled()
  })
})

describe('useEnableReleaseSource', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUpdate.mockResolvedValue({ ...sampleSources[0], enabled: false })
  })

  it('mutates with correct parameters', async () => {
    const { result } = renderHook(() => useEnableReleaseSource(), { wrapper: createWrapper() })
    result.current.mutate({ sourceId: 901, enabled: false })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mockUpdate).toHaveBeenCalledWith(901, false)
  })

  it('handles mutation error', async () => {
    mockUpdate.mockRejectedValueOnce(new Error('API error'))
    const { result } = renderHook(() => useEnableReleaseSource(), { wrapper: createWrapper() })
    result.current.mutate({ sourceId: 901, enabled: false })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error).toEqual(new Error('API error'))
  })

  it('uses injected api dependency when provided', async () => {
    const customApi = { updateReleaseSourceEnabled: vi.fn().mockResolvedValue({ ...sampleSources[0], enabled: true }) }
    const { result } = renderHook(() => useEnableReleaseSource({ api: customApi }), { wrapper: createWrapper() })
    result.current.mutate({ sourceId: 902, enabled: true })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(customApi.updateReleaseSourceEnabled).toHaveBeenCalledWith(902, true)
    expect(mockUpdate).not.toHaveBeenCalled()
  })
})