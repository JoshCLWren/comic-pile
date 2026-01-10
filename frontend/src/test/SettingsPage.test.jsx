import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import SettingsPage from '../pages/SettingsPage'
import { useSettings, useUpdateSettings } from '../hooks/useSettings'

vi.mock('../hooks/useSettings', () => ({
  useSettings: vi.fn(),
  useUpdateSettings: vi.fn(),
}))

const updateSpy = vi.fn()

beforeEach(() => {
  useSettings.mockReturnValue({
    data: {
      session_gap_hours: 6,
      start_die: 6,
      rating_min: 0.5,
      rating_max: 5.0,
      rating_step: 0.5,
      rating_threshold: 4.0,
    },
    isLoading: false,
  })
  useUpdateSettings.mockReturnValue({ mutate: updateSpy, isPending: false })
  updateSpy.mockReset()
})

it('submits updated settings', async () => {
  const user = userEvent.setup()
  render(<SettingsPage />)

  await user.clear(screen.getByLabelText(/start die/i))
  await user.type(screen.getByLabelText(/start die/i), '10')
  await user.click(screen.getByRole('button', { name: /save settings/i }))

  expect(updateSpy).toHaveBeenCalledWith({
    session_gap_hours: 6,
    start_die: 10,
    rating_min: 0.5,
    rating_max: 5,
    rating_step: 0.5,
    rating_threshold: 4,
  })
})
