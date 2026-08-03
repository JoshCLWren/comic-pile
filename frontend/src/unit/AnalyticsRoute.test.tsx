import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { expect, test, vi } from 'vitest'

const mockApiGet = vi.fn()

vi.mock('../services/api', () => ({
  default: {
    get: (...args: Parameters<typeof mockApiGet>) => mockApiGet(...args),
  },
  clearAccessToken: vi.fn(),
  setAccessToken: vi.fn(),
  getAccessToken: () => 'test-token',
}))

vi.mock('../hooks/useBugReport', () => ({
  useBugReport: () => ({ submit: vi.fn() }),
}))

vi.mock('../components/Navigation', () => ({ default: () => null }))
vi.mock('../components/BugReportButton', () => ({ default: () => null }))
vi.mock('../pages/RollPage', () => ({
  default: () => <div data-testid="roll-page">Roll</div>,
}))

import { AppRoutes, AuthProvider } from '../App'

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location-pathname">{location.pathname}</div>
}

test('redirects the retired analytics route to the root path', async () => {
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })

  render(
    <MemoryRouter initialEntries={['/analytics']}>
      <AuthProvider>
        <LocationProbe />
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>,
  )

  await waitFor(() => expect(screen.getByTestId('roll-page')).toBeInTheDocument())
  expect(screen.getByTestId('location-pathname')).toHaveTextContent('/')
})
