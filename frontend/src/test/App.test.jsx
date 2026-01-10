import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import App from '../App'

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    BrowserRouter: ({ children, basename }) => (
      <actual.MemoryRouter initialEntries={[basename ?? '/']}>{children}</actual.MemoryRouter>
    ),
  }
})

const renderApp = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  )
}

test('renders navigation labels', () => {
  renderApp()

  expect(screen.getByText('Roll')).toBeInTheDocument()
  expect(screen.getByText('Rate')).toBeInTheDocument()
  expect(screen.getByText('Queue')).toBeInTheDocument()
  expect(screen.getByText('History')).toBeInTheDocument()
  expect(screen.getByText('Analytics')).toBeInTheDocument()
})
