import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import RatePage from '../pages/RatePage'
import { rateApi, sessionApi } from '../services/api'
import { createTestQueryClient } from './testUtils'

const navigateSpy = vi.fn()

vi.mock('../components/LazyDice3D', () => ({
  default: () => <div data-testid="lazy-dice" />,
}))

vi.mock('../services/api', () => ({
  rateApi: {
    rate: vi.fn(),
  },
  sessionApi: {
    getCurrent: vi.fn(),
  },
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigateSpy,
  }
})

beforeEach(() => {
  sessionApi.getCurrent.mockResolvedValue({
    current_die: 6,
    last_rolled_result: 4,
    has_restore_point: true,
    active_thread: {
      title: 'Saga',
      format: 'Comic',
      issues_remaining: 3,
    },
  })
  rateApi.rate.mockResolvedValue({})
  navigateSpy.mockReset()
})

it('renders rate page and submits rating', async () => {
  const user = userEvent.setup()
  const queryClient = createTestQueryClient()

  render(
    <QueryClientProvider client={queryClient}>
      <RatePage />
    </QueryClientProvider>
  )

  await waitFor(() => expect(screen.getByText('Rate Session')).toBeInTheDocument())
  await user.click(await screen.findByRole('button', { name: /save & continue/i }))

  await waitFor(() => expect(rateApi.rate).toHaveBeenCalled())
  const [payload] = rateApi.rate.mock.calls[0]
  expect(payload).toEqual({
    rating: 4,
    issues_read: 1,
    finish_session: false,
  })
  await waitFor(() => expect(navigateSpy).toHaveBeenCalledWith('/'))
})
