import { test as base, type APIRequestContext } from '@playwright/test'

type AuthFixtures = {
  mockApi: {
    setupAuthUser: () => Promise<void>
    get: (path: string) => { as: (name: string) => any; reply: (status: number, body?: any) => any; networkError: (message: string) => any }
    post: (path: string) => { as: (name: string) => any; reply: (status: number, body?: any) => any }
  }
}

export const test = base.extend<AuthFixtures>({
  mockApi: async ({ page }, use) => {
    const apiMocks = new Map<string, any>()
    
    // Setup API mocking
    await page.route('**/api/**', async (route) => {
      const request = route.request()
      const url = request.url()
      const method = request.method()
      
      // Find matching mock
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
        // If no mock found, continue with the request
        await route.continue()
      }
    })

    const mockApi = {
      setupAuthUser: async () => {
        // Setup a mock authenticated user
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
        const mock = {
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
          networkError: (message: string) => {
            mock.networkError = message
            apiMocks.set(mockKey, mock)
            return mock
          }
        }
        return mock
      },

      post: (path: string) => {
        const mockKey = `POST:${path}`
        const mock = {
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
          }
        }
        return mock
      }
    }

    await use(mockApi)
  }
})

export { expect } from '@playwright/test'