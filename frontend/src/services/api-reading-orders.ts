import api from './api'

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

export const readingOrdersApi = {
  getForThread: async (threadId: number): Promise<ThreadReadingOrdersResponse> => {
    return api.get<ThreadReadingOrdersResponse>(`/v1/threads/${threadId}/reading-orders`)
  }
}
