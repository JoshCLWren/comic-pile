import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  useCreatorMetricDrilldown,
  useDrilldownPresentation,
} from '../hooks/useCreatorMetricDrilldown'
import { creatorMetricDrilldownApi } from '../services/creatorMetricDrilldownApi'
import type { CreatorMetricDrilldown } from '../types/index'

vi.mock('../services/creatorMetricDrilldownApi', () => ({
  creatorMetricDrilldownApi: {
    getMetricDrilldown: vi.fn(),
  },
}))

const mockedGetMetric = vi.mocked(creatorMetricDrilldownApi.getMetricDrilldown)

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

  it.each([
    ['rating-distribution', { ratingValue: '5.0', page: 1 }],
    ['role-stats', { role: 'writer' }],
    ['series-stats', { seriesKey: 'thread:7' }],
  ] as const)('passes %s filters through the live generic query', async (metricType, params) => {
    const { result } = renderHook(
      () => useCreatorMetricDrilldown('creator:1', metricType, params),
      { wrapper: createWrapper() },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mockedGetMetric).toHaveBeenCalledWith('creator:1', metricType, params)
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
