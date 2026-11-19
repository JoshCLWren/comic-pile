import { defaultHttpClient, type HttpClient } from './httpClient'
import type {
  CreatorMetricDrilldown,
  CreatorRatingDistributionDrilldown,
  CreatorRoleDrilldown,
  CreatorSeriesDrilldown,
} from '../types/index'

/**
 * Build the creator metric drilldown service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The creator metric drilldown API bound to `client`.
 */
export function createCreatorMetricDrilldownApi(client: HttpClient) {
  return {
    getMetricDrilldown: (
      creatorKey: string,
      metricType: string,
      params?: {
        role?: string
        ratingValue?: string
        seriesKey?: string
        page?: number
        pageSize?: number
      }
    ) =>
      client.get<CreatorMetricDrilldown>(`/v1/creators/${creatorKey}/metrics/${metricType}`, {
        params: {
          role: params?.role,
          rating_value: params?.ratingValue,
          series_key: params?.seriesKey,
          page: params?.page,
          page_size: params?.pageSize,
        },
      }),

    getRatingDistributionDrilldown: (
      creatorKey: string,
      ratingValue: string,
      params?: {
        page?: number
        pageSize?: number
      }
    ) =>
      client.get<CreatorRatingDistributionDrilldown>(
        `/v1/creators/${creatorKey}/metrics/rating-distribution/${ratingValue}`,
        {
          params: {
            page: params?.page,
            page_size: params?.pageSize,
          },
        }
      ),

    getRoleDrilldown: (
      creatorKey: string,
      role: string,
      params?: {
        page?: number
        pageSize?: number
      }
    ) =>
      client.get<CreatorRoleDrilldown>(`/v1/creators/${creatorKey}/metrics/role-stats/${role}`, {
        params: {
          page: params?.page,
          page_size: params?.pageSize,
        },
      }),

    getSeriesDrilldown: (
      creatorKey: string,
      seriesKey: string,
      params?: {
        page?: number
        pageSize?: number
      }
    ) =>
      client.get<CreatorSeriesDrilldown>(`/v1/creators/${creatorKey}/metrics/series-stats/${seriesKey}`, {
        params: {
          page: params?.page,
          page_size: params?.pageSize,
        },
      }),
  }
}

export const creatorMetricDrilldownApi = createCreatorMetricDrilldownApi(defaultHttpClient())