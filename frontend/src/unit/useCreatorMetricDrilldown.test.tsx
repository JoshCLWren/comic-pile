import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  useCreatorMetricDrilldown,
  useCreatorRatingDistributionDrilldown,
  useCreatorRoleDrilldown,
  useCreatorSeriesDrilldown,
  useDrilldownPresentation,
} from '../hooks/useCreatorMetricDrilldown'
import { creatorMetricDrilldownApi } from '../services/creatorMetricDrilldownApi'
import type { CreatorMetricDrilldown } from '../types/index'

vi.mock('../services/creatorMetricDrilldownApi', () => ({
  creatorMetricDrilldownApi: {
    getMetricDrilldown: vi.fn(),
    getRatingDistributionDrilldown: vi.fn(),
    getRoleDrilldown: vi.fn(),
    getSeriesDrilldown: vi.fn(),
  },
}))

const mockedGetMetric = vi.mocked(creatorMetricDrilldownApi.getMetricDrilldown)
const mockedGetDistribution = vi.mocked(creatorMetricDrilldownApi.getRatingDistributionDrilldown)
const mockedGetRole = vi.mocked(creatorMetricDrilldownApi.getRoleDrilldown)
const mockedGetSeries = vi.mocked(creatorMetricDrilldownApi.getSeriesDrilldown)

function makeResponse(): CreatorMetricDrilldown {
  return {
    metric_type: 'average-rating',
    creator_key: 'creator:1',
    calculation: {
      formula: '3.5 total rating points ÷ 1 rated issues = 3.50★',
      numerator: '3.5 total rating points',
      denominator: '1 rated issues',
      percentage: '3.50★',
    },
    total_count: 1,
    included_issues: [],
    excluded_issues: [],
    pagination: { page: 1, page_size: 50, next_page_token: null, total_pages: 1 },
  }
}

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedGetMetric.mockResolvedValue(makeResponse())
  mockedGetDistribution.mockResolvedValue(makeResponse())
  mockedGetRole.mockResolvedValue(makeResponse())
  mockedGetSeries.mockResolvedValue(makeResponse())
})

describe('useCreatorMetricDrilldown', () => {
  it('fetches the generic metric drilldown with the given params', async () => {
    const { result } = renderHook(
      () => useCreatorMetricDrilldown('creator:1', 'average-rating', { page: 2 }),
      { wrapper: createWrapper() },
    )

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(mockedGetMetric).toHaveBeenCalledTimes(1)
    expect(mockedGetMetric).toHaveBeenCalledWith('creator:1', 'average-rating', { page: 2 })
    expect(result.current.data?.total_count).toBe(1)
  })

  it('does not fetch without a creator key and metric type', async () => {
    renderHook(() => useCreatorMetricDrilldown('', 'average-rating'), {
      wrapper: createWrapper(),
    })

    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(mockedGetMetric).not.toHaveBeenCalled()
  })

  it('fetches distribution, role, and series drilldowns from their endpoints', async () => {
    const distribution = renderHook(
      () => useCreatorRatingDistributionDrilldown('creator:1', '5.0', { page: 1 }),
      { wrapper: createWrapper() },
    )
    const role = renderHook(() => useCreatorRoleDrilldown('creator:1', 'writer'), {
      wrapper: createWrapper(),
    })
    const series = renderHook(() => useCreatorSeriesDrilldown('creator:1', 'thread:7'), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(distribution.result.current.isPending).toBe(false))
    await waitFor(() => expect(role.result.current.isPending).toBe(false))
    await waitFor(() => expect(series.result.current.isPending).toBe(false))

    expect(mockedGetDistribution).toHaveBeenCalledWith('creator:1', '5.0', { page: 1 })
    expect(mockedGetRole).toHaveBeenCalledWith('creator:1', 'writer', undefined)
    expect(mockedGetSeries).toHaveBeenCalledWith('creator:1', 'thread:7', undefined)
  })
})

describe('useDrilldownPresentation', () => {
  it('falls back to the modal presentation without a media query match', () => {
    const { result } = renderHook(() => useDrilldownPresentation(), {
      wrapper: createWrapper(),
    })

    expect(result.current.presentation).toBe('modal')
    expect(result.current.isDesktop).toBe(false)
  })
})
