import { describe, expect, it } from 'vitest'

import { createCreatorComparisonApi } from '../services/creatorComparisonApi'
import type { CreatorComparisonResponse } from '../types/index'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const comparisonApi = createCreatorComparisonApi(client)

const RESPONSE: CreatorComparisonResponse = {
  comparisons: {},
  coverage: {
    rated_issues_total: 0,
    rated_issues_with_creator_metadata: 0,
    ratings_complete: true,
    read_unrated_issues_total: 0,
    read_unrated_issues_with_creator_metadata: 0,
    read_unrated_complete: true,
    unread_issues_total: 0,
    unread_issues_with_creator_metadata: 0,
    upcoming_complete: true,
  },
  insufficient_data_keys: [],
}

describe('creatorComparisonApi', () => {
  it('requests the bounded comparison contract with joined canonical keys', async () => {
    client.get.mockResolvedValue(RESPONSE)

    await expect(
      comparisonApi.getComparison(['creator:7', 'creator:12']),
    ).resolves.toEqual(RESPONSE)
    expect(client.get).toHaveBeenCalledWith('/v1/creators/compare', {
      params: { keys: 'creator:7,creator:12' },
    })
  })

  it('exposes only read methods so comparison cannot persist', () => {
    expect(Object.keys(comparisonApi)).toEqual([
      'getComparison',
      'getAverageDrilldown',
      'getMedianDrilldown',
      'getDistributionDrilldown',
      'getFiveStarRateDrilldown',
      'getRoleAverageDrilldown',
      'getSeriesAverageDrilldown',
      'getReadWithoutRatingDrilldown',
      'getUnreadDrilldown',
    ])
  })
})
