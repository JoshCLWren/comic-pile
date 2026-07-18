import { beforeEach, expect, it, vi } from 'vitest'
import { setAccessToken, clearAccessToken } from '../services/api'
import { readingOrdersApi } from '../services/api-reading-orders'

const originalFetch = globalThis.fetch

beforeEach(() => {
  clearAccessToken()
  globalThis.fetch = vi.fn()
})

afterAll(() => {
  globalThis.fetch = originalFetch
})

it('sends Authorization header when a token is set', async () => {
  const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>
  mockFetch.mockResolvedValue({
    ok: true,
    json: async () => ({ reading_orders: [] }),
  })

  setAccessToken('test-access-token')

  await readingOrdersApi.getForThread(42)

  expect(mockFetch).toHaveBeenCalledWith('/api/v1/threads/42/reading-orders', {
    headers: { Authorization: 'Bearer test-access-token' },
  })
})

it('does not send Authorization header when no token is set', async () => {
  const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>
  mockFetch.mockResolvedValue({
    ok: true,
    json: async () => ({ reading_orders: [] }),
  })

  await readingOrdersApi.getForThread(42)

  expect(mockFetch).toHaveBeenCalledWith('/api/v1/threads/42/reading-orders', {
    headers: {},
  })
})

it('throws an error when the response is not ok', async () => {
  const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>
  mockFetch.mockResolvedValue({
    ok: false,
    status: 401,
  })

  setAccessToken('expired-token')

  await expect(readingOrdersApi.getForThread(42)).rejects.toThrow(
    'Failed to fetch reading orders: 401',
  )
})
