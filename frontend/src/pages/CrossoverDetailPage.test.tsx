import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { rest } from 'msw'
import { setupServer } from 'msw/node'
import CrossoverDetailPage from './CrossoverDetailPage'

// Mock API response data
const detail = {
  id: 1,
  name: 'Test Crossover',
  created_at: '2024-01-01T00:00:00Z',
  memberships: [
    {
      membership: {
        id: 10,
        thread_id: 5,
        issue_id: null,
        sequence_order: 1,
      },
      thread: {
        id: 5,
        title: 'Series A',
        description: 'Desc',
        start_year: 2020,
        status: 'ongoing',
        notes: null,
        rating: null,
        created_at: '2024-01-01T00:00:00Z',
      },
      issue: null,
      other_crossovers: ['B'],
    },
  ],
  linked_plans: [],
}

const server = setupServer(
  rest.get('/api/v1/reading-order-groups/:id/detail', (req, res, ctx) => {
    return res(ctx.json(detail))
  }),
)

// Enable API mocking before tests.
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
// Reset any request handlers that are declared as a part of our tests.
afterEach(() => server.resetHandlers())
// Disable API mocking after the tests are done.
afterAll(() => server.close())

// Helper to render with QueryClientProvider
function renderWithProviders(ui: React.ReactElement, route: string = '/crossovers/1') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}


test('renders crossover details after loading', async () => {
  renderWithProviders(<CrossoverDetailPage />)
  // Wait for the headline to appear
  await waitFor(() => {
    expect(screen.getByText('Test Crossover')).toBeInTheDocument()
  })
  // Check that member row exists
  expect(screen.getByText('Series A')).toBeInTheDocument()
})

test('renders error page on server error', async () => {
  server.use(
    rest.get('/api/v1/reading-order-groups/:id/detail', (req, res, ctx) => {
      return res(ctx.status(500))
    }),
  )
  renderWithProviders(<CrossoverDetailPage />)
  await waitFor(() => {
    expect(screen.getByText('Error loading crossover')).toBeInTheDocument()
  })
})
