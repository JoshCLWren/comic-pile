import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useActivity } from '../hooks/useActivity'
import { activityApi, type ActivityEvent } from '../services/api-activity'

vi.mock('../services/api-activity', () => ({ activityApi: { list: vi.fn() } }))
const list = vi.mocked(activityApi.list)

beforeEach(() => vi.clearAllMocks())

function event(event_id: number): ActivityEvent {
  return {
    event_id, event_type: 'roll', timestamp: '2026-11-08T15:42:35Z',
    die_before: 6, die_after: null, rating: null, thread_id: 1,
    thread_title: 'First Series', issue_id: 1, issue_number: '1',
    action_display: 'Rolled First Series #1',
  }
}

it('continues with the server cursor and refreshes the same activity query', async () => {
  list.mockImplementation(async (token) => token
    ? { events: [event(2)], next_page_token: null }
    : { events: [event(1)], next_page_token: '123:1' })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  const { result } = renderHook(() => useActivity(), { wrapper })
  await waitFor(() => expect(result.current.events.map((event) => event.event_id)).toEqual([1]))
  await act(async () => { await result.current.loadMore() })
  await waitFor(() => expect(result.current.events.map((event) => event.event_id)).toEqual([1, 2]))
  expect(list).toHaveBeenNthCalledWith(1, null, 50)
  expect(list).toHaveBeenNthCalledWith(2, '123:1', 50)
  await act(async () => { await result.current.refetch() })
  expect(list).toHaveBeenCalledWith(null, 50)
})
