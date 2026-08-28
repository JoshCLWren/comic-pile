import api from './api'
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

export const readingOrdersApi = {
  list: async (): Promise<ReadingOrderListResponse> => {
    return api.get<ReadingOrderListResponse>('/v1/reading-orders/')
  },
  insertItem: async (
    readingOrderId: number,
    data: { thread_id: number; position: number },
  ): Promise<InsertReadingOrderItemResponse> => {
    return api.post<InsertReadingOrderItemResponse>(
      `/v1/reading-orders/${readingOrderId}/items`,
      data,
    )
  },
  previewProjection: async (
    planId: number,
    readingOrderId: number,
  ): Promise<ReadingOrderProjectionPreview> => {
    return api.post<ReadingOrderProjectionPreview>(
      `/v1/continuity-plans/${planId}/reading-orders/project-preview`,
      { reading_order_id: readingOrderId },
    )
  },
  confirmProjection: async (
    planId: number,
    readingOrderId: number,
  ): Promise<ReadingOrderProjectionResult> => {
    return api.post<ReadingOrderProjectionResult>(
      `/v1/continuity-plans/${planId}/reading-orders/project`,
      { reading_order_id: readingOrderId },
    )
  },
  getForThread: async (threadId: number): Promise<ThreadReadingOrdersResponse> => {
    return api.get<ThreadReadingOrdersResponse>(`/v1/threads/${threadId}/reading-orders`)
  },
  adoptReadingOrder: async (params: {
    readingOrderId: number
    planName?: string
    laneId?: string
    laneName?: string
  }): Promise<ContinuityPlan> => {
    return api.post(`/v1/continuity-plans/from-reading-order`, {
      reading_order_id: params.readingOrderId,
      plan_name: params.planName ?? null,
      lane_id: params.laneId ?? 'adopted',
      lane_name: params.laneName ?? 'Adopted',
    })
  },
}
