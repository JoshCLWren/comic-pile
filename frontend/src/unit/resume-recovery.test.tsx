import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import axios from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ResumeRecovery from '../components/ResumeRecovery'

const { revalidateSession, recoverSession, invalidateQueries } = vi.hoisted(() => ({
  revalidateSession: vi.fn(),
  recoverSession: vi.fn(),
  invalidateQueries: vi.fn(),
}))

vi.mock('../query/queryClient', () => ({
  queryClient: { invalidateQueries },
}))

function createAxiosError(status: number, message: string): Error {
  const error = new Error(message) as Error & { response?: { status: number } }
  error.response = { status }
  return error
}

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

function renderRecovery() {
  return render(
    <ResumeRecovery revalidateSession={revalidateSession} recoverSession={recoverSession}>
      <div>Last usable screen</div>
    </ResumeRecovery>,
  )
}

describe('ResumeRecovery', () => {
  beforeEach(() => {
    revalidateSession.mockReset()
    recoverSession.mockReset()
    invalidateQueries.mockReset()
    setVisibilityState('visible')
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('revalidates auth and cached application data after a BFCache restore', async () => {
    revalidateSession.mockResolvedValue(undefined)
    invalidateQueries.mockResolvedValue(undefined)

    renderRecovery()
    dispatchPageShow(true)

    expect(screen.getByText('Last usable screen')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Reconnecting ComicPile')
    await waitFor(() => expect(revalidateSession).toHaveBeenCalledWith(15000))
    await waitFor(() => expect(invalidateQueries).toHaveBeenCalledOnce())
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
    expect(recoverSession).not.toHaveBeenCalled()
  })

  it('keeps the application visible and offers recovery after bounded retries fail', async () => {
    vi.useFakeTimers()
    revalidateSession.mockRejectedValue(new Error('network suspended'))

    renderRecovery()
    dispatchPageShow(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })

    expect(revalidateSession).toHaveBeenCalledTimes(2)
    expect(screen.getByText('Last usable screen')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('ComicPile could not reconnect')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
  })

  it('retries 503 errors many times with exponential backoff and never shows failed state', async () => {
    vi.useFakeTimers()
    const serviceUnavailableError = createAxiosError(503, 'Service Unavailable')
    revalidateSession.mockRejectedValue(serviceUnavailableError)

    renderRecovery()
    dispatchPageShow(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(100)
    })

    expect(revalidateSession).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })

    expect(revalidateSession).toHaveBeenCalledTimes(2)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })

    expect(revalidateSession).toHaveBeenCalledTimes(3)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000)
    })

    expect(revalidateSession).toHaveBeenCalledTimes(4)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000)
    })

    expect(screen.getByRole('status')).toHaveTextContent('Reconnecting ComicPile')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(16000)
    })

    expect(revalidateSession).toHaveBeenCalledTimes(6)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows reconnecting UI after 8 seconds for 503 errors in automatic mode', async () => {
    vi.useFakeTimers()
    const serviceUnavailableError = createAxiosError(503, 'Service Unavailable')
    revalidateSession.mockRejectedValue(serviceUnavailableError)

    renderRecovery()
    dispatchPageShow(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(7999)
    })

    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })

    expect(screen.getByRole('status')).toHaveTextContent('Reconnecting ComicPile')
  })

  it('shows reconnecting UI after 3 seconds for non-503 errors in automatic mode', async () => {
    vi.useFakeTimers()
    revalidateSession.mockRejectedValue(new Error('network error'))

    renderRecovery()
    dispatchPageShow(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2999)
    })

    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })

    expect(screen.getByRole('status')).toHaveTextContent('Reconnecting ComicPile')
  })

  it('runs an explicit auth recovery immediately even inside the automatic throttle window', async () => {
    vi.useFakeTimers()
    const now = vi.spyOn(Date, 'now').mockReturnValue(10_000)
    revalidateSession.mockRejectedValue(new Error('server still waking'))
    recoverSession.mockResolvedValue(undefined)
    invalidateQueries.mockResolvedValue(undefined)

    renderRecovery()
    dispatchPageShow(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(750)
    })
    expect(screen.getByRole('alert')).toHaveTextContent('ComicPile could not reconnect')

    now.mockReturnValue(10_500)
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))

    expect(screen.getByRole('status')).toHaveTextContent('Reconnecting ComicPile')
    expect(recoverSession).toHaveBeenCalledWith(15000)
    expect(revalidateSession).toHaveBeenCalledTimes(2)

    await act(async () => {
      await Promise.resolve()
    })
    expect(invalidateQueries).toHaveBeenCalledOnce()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('does not allow automatic lifecycle events to supersede an explicit retry', async () => {
    vi.useFakeTimers()
    let finishExplicitRecovery: (() => void) | undefined
    revalidateSession.mockRejectedValue(new Error('resume failed'))
    recoverSession.mockImplementation(
      () => new Promise<void>((resolve) => {
        finishExplicitRecovery = resolve
      }),
    )
    invalidateQueries.mockResolvedValue(undefined)

    renderRecovery()
    dispatchPageShow(true)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(750)
    })

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(recoverSession).toHaveBeenCalledOnce()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100)
    })
    fireEvent(document, new Event('visibilitychange'))
    dispatchPageShow(true)
    expect(revalidateSession).toHaveBeenCalledTimes(2)

    await act(async () => {
      finishExplicitRecovery?.()
    })

    expect(invalidateQueries).toHaveBeenCalledOnce()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('ignores ordinary page shows and hidden tabs, then recovers on a visible resume with one successful retry', async () => {
    vi.useFakeTimers()
    revalidateSession
      .mockRejectedValueOnce(new Error('radio still waking'))
      .mockResolvedValueOnce(undefined)
    invalidateQueries.mockResolvedValue(undefined)

    renderRecovery()

    dispatchPageShow(false)
    setVisibilityState('hidden')
    fireEvent(document, new Event('visibilitychange'))
    expect(revalidateSession).not.toHaveBeenCalled()

    setVisibilityState('visible')
    fireEvent(document, new Event('visibilitychange'))
    dispatchPageShow(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(750)
    })

    expect(revalidateSession).toHaveBeenCalledTimes(2)
    expect(invalidateQueries).toHaveBeenCalledOnce()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('does not let an older invalidation hide a newer recovery attempt', async () => {
    let finishFirstInvalidation: (() => void) | undefined
    const now = vi.spyOn(Date, 'now').mockReturnValue(10_000)
    revalidateSession.mockResolvedValue(undefined)
    invalidateQueries
      .mockImplementationOnce(
        () => new Promise<void>((resolve) => {
          finishFirstInvalidation = resolve
        }),
      )
      .mockResolvedValueOnce(undefined)

    renderRecovery()
    dispatchPageShow(true)
    await waitFor(() => expect(invalidateQueries).toHaveBeenCalledOnce())

    now.mockReturnValue(11_001)
    fireEvent(document, new Event('visibilitychange'))
    await waitFor(() => expect(revalidateSession).toHaveBeenCalledTimes(2))

    await act(async () => {
      finishFirstInvalidation?.()
    })

    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  })

  it('treats 503 on explicit retry as a regular error with bounded attempts', async () => {
    vi.useFakeTimers()
    const serviceUnavailableError = createAxiosError(503, 'Service Unavailable')
    revalidateSession.mockRejectedValue(serviceUnavailableError)
    recoverSession.mockRejectedValue(serviceUnavailableError)

    renderRecovery()
    dispatchPageShow(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })

    expect(screen.getByRole('alert')).toHaveTextContent('ComicPile could not reconnect')

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(750)
    })

    expect(recoverSession).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(750)
    })

    expect(recoverSession).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('alert')).toHaveTextContent('ComicPile could not reconnect')
  })
})