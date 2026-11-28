import { defaultHttpClient, type HttpClient } from './httpClient'
import type { CreatorMetricDrilldown } from '../types/index'

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
      client.get<CreatorMetricDrilldown>(`/v2/creators/${creatorKey}/metrics/${metricType}`, {
        params: {
          role: params?.role,
          rating_value: params?.ratingValue,
          series_key: params?.seriesKey,
          page: params?.page,
          page_size: params?.pageSize,
        },
      }),

  }
}

export const creatorMetricDrilldownApi = createCreatorMetricDrilldownApi(defaultHttpClient())