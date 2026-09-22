import { test as base } from '@playwright/test'

type QueuedResponse = {
  status: number
  body: unknown
  networkError: string | null
}

type MockObject = {
  name?: string
  as: (name: string) => MockObject
  reply: (status: number, body?: unknown) => MockObject
  replyOnce: (status: number, body?: unknown) => MockObject
  networkErrorMethod: (message: string) => MockObject
}

type AuthFixtures = {
  mockApi: {
    setupAuthUser: () => Promise<void>
    get: (path: string) => MockObject
    post: (path: string) => MockObject
  }
}

function normalizePath(path: string): string {
  return path.replace(/^\/api/, '')
}

export const test = base.extend<AuthFixtures>({
  mockApi: async ({ page }, use) => {
    const apiQueues = new Map<string, QueuedResponse[]>()

    function queueKey(method: string, path: string): string {
      return `${method}:${normalizePath(path)}`
    }

    function findQueueForRequest(method: string, url: string): QueuedResponse[] | undefined {
      for (const [key, queue] of apiQueues.entries()) {
        const [queueMethod, queuePath] = key.split(':', 2)
        if (queueMethod !== method) continue
        if (url.includes(queuePath)) return queue
      }
      return undefined
    }

    await page.route('**/api/**', async (route) => {
      const request = route.request()
      const url = request.url()
      const method = request.method()

      const queue = findQueueForRequest(method, url)

      if (queue && queue.length > 0) {
        const next = queue.shift()!
        if (next.networkError) {
          await route.abort('failed')
        } else {
          await route.fulfill({
            status: next.status,
            contentType: 'application/json',
            body: JSON.stringify(next.body ?? {}),
          })
        }
        return
      }

      await route.continue()
    })

    function createMock(method: string, path: string): MockObject {
      const key = queueKey(method, path)
      if (!apiQueues.has(key)) apiQueues.set(key, [])
      const queue = apiQueues.get(key)!

      const mock: MockObject = {
        as: (name: string) => {
          mock.name = name
          return mock
        },
        reply: (status: number, body?: unknown) => {
          queue.length = 0
          queue.push({ status, body: body ?? null, networkError: null })
          return mock
        },
        replyOnce: (status: number, body?: unknown) => {
          queue.push({ status, body: body ?? null, networkError: null })
          return mock
        },
        networkErrorMethod: (message: string) => {
          queue.push({ status: 0, body: null, networkError: message || 'failed' })
          return mock
        },
      }
      return mock
    }

    const mockApi = {
      setupAuthUser: async () => {
        mockApi.post('/api/v1/auth/login').as('login').reply(200, {
          access_token: 'test-access-token',
          refresh_token: 'test-refresh-token',
        })

        mockApi.get('/api/v1/auth/me').as('authMe').reply(200, {
          id: 1,
          username: 'testuser',
          email: 'test@example.com',
          created_at: '2023-01-01T00:00:00Z',
          last_login: '2023-01-01T00:00:00Z',
          preferences: { theme: 'classic' },
        })
      },

      get: (path: string) => createMock('GET', path),
      post: (path: string) => createMock('POST', path),
    }

    await use(mockApi)
  },
})

export { expect } from '@playwright/test'
