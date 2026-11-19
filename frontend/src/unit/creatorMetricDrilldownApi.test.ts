import { describe, expect, it } from 'vitest'

import { queryKeys } from '../query/queryKeys'
import { createCreatorMetricDrilldownApi } from '../services/creatorMetricDrilldownApi'
import type { CreatorMetricDrilldown } from '../types/index'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const drilldownApi = createCreatorMetricDrilldownApi(client)

const DRILLDOWN: CreatorMetricDrilldown = {
  metric_type: 'average-rating',
  creator_key: 'creator:1',
  calculation: {
    formula: '9.0 total rating points ÷ 2 rated issues = 4.50★',
    numerator: '9.0 total rating points',
    denominator: '2 rated issues',
    percentage: '4.50★',
  },
  total_count: 2,
  included_issues: [],
  excluded_issues: [],
  pagination: { page: 1, page_size: 50, next_page_token: null, total_pages: 1 },
}

describe('creatorMetricDrilldownApi', () => {
  it('requests the generic metric drilldown with snake_case params', async () => {
    client.get.mockResolvedValue(DRILLDOWN)

    await expect(
      drilldownApi.getMetricDrilldown('creator:1', 'average-rating', { page: 2, pageSize: 25 }),
    ).resolves.toEqual(DRILLDOWN)
    expect(client.get).toHaveBeenCalledWith('/v1/creators/creator:1/metrics/average-rating', {
      params: {
        role: undefined,
        rating_value: undefined,
        series_key: undefined,
        page: 2,
        page_size: 25,
      },
    })
  })

  it('maps role, rating, and series params to the generic endpoint', async () => {
    client.get.mockResolvedValue(DRILLDOWN)

    await drilldownApi.getMetricDrilldown('creator:1', 'role-stats', {
      role: 'writer',
      ratingValue: '5.0',
      seriesKey: 'thread:7',
    })
    expect(client.get).toHaveBeenCalledWith('/v1/creators/creator:1/metrics/role-stats', {
      params: {
        role: 'writer',
        rating_value: '5.0',
        series_key: 'thread:7',
        page: undefined,
        page_size: undefined,
      },
    })
  })

  it('requests rating distribution buckets from the dedicated endpoint', async () => {
    client.get.mockResolvedValue(DRILLDOWN)

    await drilldownApi.getRatingDistributionDrilldown('creator:1', '5.0', { page: 1 })
    expect(client.get).toHaveBeenCalledWith(
      '/v1/creators/creator:1/metrics/rating-distribution/5.0',
      { params: { page: 1, page_size: undefined } },
    )
  })

  it('requests role and series drilldowns from their dedicated endpoints', async () => {
    client.get.mockResolvedValue(DRILLDOWN)

    await drilldownApi.getRoleDrilldown('creator:1', 'writer', { pageSize: 10 })
    expect(client.get).toHaveBeenCalledWith('/v1/creators/creator:1/metrics/role-stats/writer', {
      params: { page: undefined, page_size: 10 },
    })

    await drilldownApi.getSeriesDrilldown('creator:1', 'thread:7', {})
    expect(client.get).toHaveBeenCalledWith(
      '/v1/creators/creator:1/metrics/series-stats/thread:7',
      { params: { page: undefined, page_size: undefined } },
    )
  })

  it('exposes only read methods so drilldowns cannot persist', () => {
    expect(Object.keys(drilldownApi).sort()).toEqual([
      'getMetricDrilldown',
      'getRatingDistributionDrilldown',
      'getRoleDrilldown',
      'getSeriesDrilldown',
    ])
  })
})

describe('creator drilldown query keys', () => {
  it('builds a canonical metric key that drops undefined params', () => {
    expect(queryKeys.creators.metric('creator:1', 'average-rating', { page: 1 })).toEqual([
      'creators',
      'metric',
      'creator:1',
      'average-rating',
      { page: 1 },
    ])
    expect(
      queryKeys.creators.metric('creator:1', 'average-rating', {
        page: undefined,
        pageSize: undefined,
      }),
    ).toEqual(['creators', 'metric', 'creator:1', 'average-rating', {}])
  })

  it('builds distinct keys per drilldown family', () => {
    expect(queryKeys.creators.ratingDistribution('creator:1', '5.0', {})).toEqual([
      'creators',
      'ratingDistribution',
      'creator:1',
      '5.0',
      {},
    ])
    expect(queryKeys.creators.roleStats('creator:1', 'writer', {})).toEqual([
      'creators',
      'roleStats',
      'creator:1',
      'writer',
      {},
    ])
    expect(queryKeys.creators.seriesStats('creator:1', 'thread:7', {})).toEqual([
      'creators',
      'seriesStats',
      'creator:1',
      'thread:7',
      {},
    ])
  })
})
