import { getAccessToken } from './api'

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

function getAuthHeaders(): Record<string, string> {
  const token = getAccessToken()
  if (token) {
    return { 'Authorization': `Bearer ${token}` }
  }
  return {}
}

export const readingOrdersApi = {
  getForThread: async (threadId: number): Promise<ThreadReadingOrdersResponse> => {
    const response = await fetch(`/api/v1/threads/${threadId}/reading-orders`, {
      headers: getAuthHeaders(),
    })
    if (!response.ok) {
      throw new Error(`Failed to fetch reading orders: ${response.status}`)
    }
    return response.json()
  }
}
