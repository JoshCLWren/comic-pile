import { test as base } from '@playwright/test'

type MockObject = {
  status: number
  body: any
  networkError: string | null
  pending: boolean
  name?: string
  as: (name: string) => MockObject
  reply: (status: number, body?: any) => MockObject
  networkErrorMethod: (message: string) => MockObject
}

type AuthFixtures = {
  mockApi: {
    setupAuthUser: () => Promise<void>
    get: (path: string) => MockObject
    post: (path: string) => MockObject
  }
}

export const test = base.extend<AuthFixtures>({
  mockApi: async ({ page }, use) => {
    const apiMocks = new Map<string, MockObject>()
    
    await page.route('**/api/**', async (route) => {
      const request = route.request()
      const url = request.url()
      const method = request.method()
      
      const mockKey = `${method}:${url}`
      const mock = apiMocks.get(mockKey)
      
      if (mock && mock.pending) {
        mock.pending = false
        if (mock.networkError) {
          await route.abort(mock.networkError)
        } else {
          await route.fulfill({
            status: mock.status,
            contentType: 'application/json',
            body: JSON.stringify(mock.body || {}),
          })
        }
      } else {
        await route.continue()
      }
    })

    const mockApi = {
      setupAuthUser: async () => {
        await mockApi.post('/api/v1/auth/login')
          .as('login')
          .reply(200, {
            access_token: 'test-access-token',
            refresh_token: 'test-refresh-token'
          })
        
        await mockApi.get('/api/v1/auth/me')
          .as('authMe')
          .reply(200, {
            id: 1,
            username: 'testuser',
            email: 'test@example.com',
            created_at: '2023-01-01T00:00:00Z',
            last_login: '2023-01-01T00:00:00Z',
            preferences: { theme: 'classic' }
          })
      },

      get: (path: string) => {
        const mockKey = `GET:${path}`
        const mock: MockObject = {
          status: 200,
          body: null,
          networkError: null,
          pending: true,
          as: (name: string) => {
            mock.name = name
            return mock
          },
          reply: (status: number, body?: any) => {
            mock.status = status
            mock.body = body
            apiMocks.set(mockKey, mock)
            return mock
          },
          networkErrorMethod: (message: string) => {
            mock.networkError = message
            apiMocks.set(mockKey, mock)
            return mock
          }
        }
        return mock
      },

      post: (path: string) => {
        const mockKey = `POST:${path}`
        const mock: MockObject = {
          status: 200,
          body: null,
          networkError: null,
          pending: true,
          as: (name: string) => {
            mock.name = name
            return mock
          },
          reply: (status: number, body?: any) => {
            mock.status = status
            mock.body = body
            apiMocks.set(mockKey, mock)
            return mock
          },
          networkErrorMethod: () => mock
        }
        return mock
      }
    }

    await use(mockApi)
  }
})

export { expect } from '@playwright/test'