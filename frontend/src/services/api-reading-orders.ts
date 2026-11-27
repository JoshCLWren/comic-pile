import { defaultHttpClient, type HttpClient } from './httpClient'
import type { ContinuityPlan } from './api-continuity-plans'

export interface ReadingOrderItem {
  thread_id: number
  thread_title: string
  position: number
  issue_number: string | null
  is_read: boolean
}

export interface ReadingOrder {
  id: number
  name: string
  description: string | null
  total_items: number
  completed_items: number
  items: ReadingOrderItem[]
}

export interface ThreadReadingOrdersResponse {
  reading_orders: ReadingOrder[]
}

export interface ReadingOrderSummary {
  id: number
  name: string
  description: string | null
  total_items: number
}

export interface ReadingOrderListResponse {
  reading_orders: ReadingOrderSummary[]
}

export interface ReadingOrderProjectionEntry {
  thread_id: number
  thread_title: string | null
  position: number
  source: 'existing' | 'added' | 'updated'
  source_node_id: string | null
}

export interface ReadingOrderProjectionConflict {
  code: 'duplicate_thread' | 'missing_thread' | 'non_thread_node'
  message: string
  node_id: string
  thread_id: number | null
  existing_positions: number[]
}

export interface ReadingOrderProjectionPreview {
  plan_id: number
  plan_name: string
  plan_ordering_mode: string
  reading_order_id: number
  reading_order_name: string
  entries: ReadingOrderProjectionEntry[]
  conflicts: ReadingOrderProjectionConflict[]
  total_positions: number
  dropped_node_ids: string[]
}

export interface ReadingOrderProjectionResult {
  plan_id: number
  reading_order_id: number
  added_count: number
  updated_count: number
  kept_count: number
  total_positions: number
}

export interface InsertReadingOrderItemResponse {
  reading_order_id: number
  thread_id: number
  position: number
  total_items: number
}

/**
 * Build the reading-order service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The reading-order service bound to `client`.
 */
export function createReadingOrdersApi(client: HttpClient) {
  return {
    list: async (): Promise<ReadingOrderListResponse> => {
      return client.get<ReadingOrderListResponse>('/v2/reading-orders/')
    },
    insertItem: async (
      readingOrderId: number,
      data: { thread_id: number; position: number },
    ): Promise<InsertReadingOrderItemResponse> => {
      return client.post<InsertReadingOrderItemResponse>(
        `/v2/reading-orders/${readingOrderId}/items`,
        data,
      )
    },
    /**
     * Stateless AIP-136 resource custom method (#5715). Preview recomputes from
     * the plan on every call and writes nothing; the retained v1 preview URL is
     * not used by any caller.
     */
    previewProjection: async (
      planId: number,
      readingOrderId: number,
    ): Promise<ReadingOrderProjectionPreview> => {
      return client.post<ReadingOrderProjectionPreview>(
        `/v2/continuityPlans/${planId}:previewReadingOrderProjection`,
        { reading_order_id: readingOrderId },
      )
    },
    confirmProjection: async (
      planId: number,
      readingOrderId: number,
    ): Promise<ReadingOrderProjectionResult> => {
      return client.post<ReadingOrderProjectionResult>(
        `/v2/continuity-plans/${planId}/reading-orders/project`,
        { reading_order_id: readingOrderId },
      )
    },
    /** Canonical AIP-122 collection spelling of the owner-scoped read (#5715). */
    getForThread: async (threadId: number): Promise<ThreadReadingOrdersResponse> => {
      return client.get<ThreadReadingOrdersResponse>(`/v2/threads/${threadId}/readingOrders`)
    },
    adoptReadingOrder: async (params: {
      readingOrderId: number
      planName?: string
      laneId?: string
      laneName?: string
    }): Promise<ContinuityPlan> => {
      return client.post(`/v2/continuity-plans/from-reading-order`, {
        reading_order_id: params.readingOrderId,
        plan_name: params.planName ?? null,
        lane_id: params.laneId ?? 'adopted',
        lane_name: params.laneName ?? 'Adopted',
      })
    },
  }
}

export const readingOrdersApi = createReadingOrdersApi(defaultHttpClient())
