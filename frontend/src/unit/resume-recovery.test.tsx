import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ResumeRecovery from '../components/ResumeRecovery'

const apiGet = vi.fn()
const invalidateQueries = vi.fn()

vi.mock('../services/api', () => ({
  default: { get: apiGet },
}))

vi.mock('../query/queryClient', () => ({
  queryClient: { invalidateQueries },
}))

function dispatchPersistedPageShow(): void {
  const event = new Event('pageshow')
  Object.defineProperty(event, 'persisted', { value: true })
  fireEvent(window, event)
}

describe('ResumeRecovery', () => {
  beforeEach(() => {
    apiGet.mockReset()
    invalidateQueries.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('revalidates auth and cached application data after a BFCache restore', async () => {
    apiGet.mockResolvedValue({ id: 1 })
    invalidateQueries.mockResolvedValue(undefined)

    render(<ResumeRecovery><div>Last usable screen</div></ResumeRecovery>)
    dispatchPersistedPageShow()

    expect(screen.getByText('Last usable screen')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Reconnecting ComicPile')
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/v1/auth/me', expect.objectContaining({ timeout: 8000 })))
    await waitFor(() => expect(invalidateQueries).toHaveBeenCalledOnce())
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  })

  it('keeps the application visible and offers recovery after bounded retries fail', async () => {
    vi.useFakeTimers()
    apiGet.mockRejectedValue(new Error('network suspended'))

    render(<ResumeRecovery><div>Last usable screen</div></ResumeRecovery>)
    dispatchPersistedPageShow()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })

    expect(apiGet).toHaveBeenCalledTimes(2)
    expect(screen.getByText('Last usable screen')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('ComicPile could not reconnect')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
  })
})
