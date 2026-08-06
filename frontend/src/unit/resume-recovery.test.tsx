import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ResumeRecovery from '../components/ResumeRecovery'

const { apiGet, invalidateQueries } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  invalidateQueries: vi.fn(),
}))

vi.mock('../services/api', () => ({
  default: { get: apiGet },
}))

vi.mock('../query/queryClient', () => ({
  queryClient: { invalidateQueries },
}))

function dispatchPageShow(persisted: boolean): void {
  const event = new Event('pageshow')
  Object.defineProperty(event, 'persisted', { value: persisted })
  fireEvent(window, event)
}

function setVisibilityState(state: DocumentVisibilityState): void {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    value: state,
  })
}

describe('ResumeRecovery', () => {
  beforeEach(() => {
    apiGet.mockReset()
    invalidateQueries.mockReset()
    setVisibilityState('visible')
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('revalidates auth and cached application data after a BFCache restore', async () => {
    apiGet.mockResolvedValue({ id: 1 })
    invalidateQueries.mockResolvedValue(undefined)

    render(<ResumeRecovery><div>Last usable screen</div></ResumeRecovery>)
    dispatchPageShow(true)

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
    dispatchPageShow(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })

    expect(apiGet).toHaveBeenCalledTimes(2)
    expect(screen.getByText('Last usable screen')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('ComicPile could not reconnect')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
  })

  it('ignores ordinary page shows and hidden tabs, then recovers on a visible resume with one successful retry', async () => {
    vi.useFakeTimers()
    apiGet
      .mockRejectedValueOnce(new Error('radio still waking'))
      .mockResolvedValueOnce({ id: 1 })
    invalidateQueries.mockResolvedValue(undefined)

    render(<ResumeRecovery><div>Last usable screen</div></ResumeRecovery>)

    dispatchPageShow(false)
    setVisibilityState('hidden')
    fireEvent(document, new Event('visibilitychange'))
    expect(apiGet).not.toHaveBeenCalled()

    setVisibilityState('visible')
    fireEvent(document, new Event('visibilitychange'))
    dispatchPageShow(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(750)
    })

    expect(apiGet).toHaveBeenCalledTimes(2)
    expect(invalidateQueries).toHaveBeenCalledOnce()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
