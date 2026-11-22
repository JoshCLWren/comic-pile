import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import api, { getAccessToken, setAccessToken } from '../services/api'
import { AppRoutes, AuthProvider } from '../App'
import { ToastProvider } from '../contexts/ToastProvider'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'
import { NavCollapseProvider } from '../contexts/NavCollapseContext'

const originalApiGet = api.get
const originalAccessToken = getAccessToken()
const mockApiGet = vi.fn<typeof api.get>()

afterEach(() => {
  Object.assign(api, { get: originalApiGet })
  setAccessToken(originalAccessToken)
  mockApiGet.mockReset()
})

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location-pathname">{location.pathname}</div>
}

test('redirects the retired analytics route to the root path', async () => {
  Object.assign(api, { get: mockApiGet })
  setAccessToken('test-token')
  mockApiGet.mockImplementation((url) => {
    if (url === '/v2/auth/me') {
      return Promise.resolve({ username: 'testuser', email: 'test@test.com' })
    }
    // Keep Roll's independent resource queries pending: this route regression
    // needs the real root page to mount, not a complete library fixture.
    return new Promise(() => undefined)
  })

  render(
    <MemoryRouter initialEntries={['/analytics']}>
      <BugReportRestoreProvider>
        <ToastProvider>
          <AuthProvider>
            <NavCollapseProvider>
              <LocationProbe />
              <AppRoutes />
            </NavCollapseProvider>
          </AuthProvider>
        </ToastProvider>
      </BugReportRestoreProvider>
    </MemoryRouter>,
  )

  await waitFor(() => expect(screen.getByText('Loading...', { exact: true })).toBeInTheDocument())
  expect(screen.getByTestId('location-pathname')).toHaveTextContent('/')
})
