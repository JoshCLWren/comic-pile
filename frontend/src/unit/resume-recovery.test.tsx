import { act, fireEvent, render, screen } from '@testing-library/react'
import axios from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ResumeRecovery, {
  RESUME_INITIAL_RETRY_DELAY_MS,
  RESUME_MAX_ATTEMPTS,
  RESUME_MAX_BACKOFF_MS,
  RESUME_RECONNECTING_GRACE_MS,
} from '../components/ResumeRecovery'

const { revalidateSession, recoverSession, invalidateQueries } = vi.hoisted(() => ({
  revalidateSession: vi.fn(),
  recoverSession: vi.fn(),
  invalidateQueries: vi.fn(),
}))

vi.mock('../query/queryClient', () => ({
  queryClient: { invalidateQueries },
}))

function totalTransientBackoff(): number {
  let total = 0
  for (let attempt = 1; attempt < RESUME_MAX_ATTEMPTS; attempt += 1) {
    total += Math.min(RESUME_INITIAL_RETRY_DELAY_MS * 2 ** (attempt - 1), RESUME_MAX_BACKOFF_MS)
  }
  return total
}

function axiosError(status?: number): Error {
  const error = new axios.AxiosError('Request failed', 'ERR_BAD_RESPONSE')
  if (status !== undefined) {
    ;(error as unknown as { response: { status: number; data: object } }).response = {
      status,
      data: {},
    }
  }
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

  it('stays completely invisible when a reconnect resolves faster than the grace period', async () => {
    vi.useFakeTimers()
    revalidateSession.mockResolvedValue(undefined)
    invalidateQueries.mockResolvedValue(undefined)

    renderRecovery()
    dispatchPageShow(true)

    await act(async () => {
      await Promise.resolve()
    })

    expect(revalidateSession).toHaveBeenCalledWith(15000)
    expect(invalidateQueries).toHaveBeenCalledOnce()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('Last usable screen')).toBeInTheDocument()
  })

  it('keeps the application visible and only surfaces an error after patient retries exhaust', async () => {
    vi.useFakeTimers()
    revalidateSession.mockRejectedValue(new Error('network suspended'))

    renderRecovery()
    dispatchPageShow(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(RESUME_RECONNECTING_GRACE_MS + totalTransientBackoff())
    })

    expect(revalidateSession).toHaveBeenCalledTimes(RESUME_MAX_ATTEMPTS)
    expect(screen.getByText('Last usable screen')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('ComicPile could not reconnect')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
  })

  it('treats a 503 cold start as transient and recovers invisibly with a retry', async () => {
    vi.useFakeTimers()
    revalidateSession
      .mockRejectedValueOnce(axiosError(503))
      .mockResolvedValueOnce(undefined)
    invalidateQueries.mockResolvedValue(undefined)

    renderRecovery()
    dispatchPageShow(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(RESUME_INITIAL_RETRY_DELAY_MS)
    })

    expect(revalidateSession).toHaveBeenCalledTimes(2)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(invalidateQueries).toHaveBeenCalledOnce()
  })

  it('surfaces an error immediately for a definitive authentication rejection', async () => {
    vi.useFakeTimers()
    revalidateSession.mockRejectedValue(axiosError(401))

    renderRecovery()
    dispatchPageShow(true)

    await act(async () => {
      await Promise.resolve()
    })

    expect(screen.getByRole('alert')).toHaveTextContent('ComicPile could not reconnect')
    expect(revalidateSession).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('runs an explicit auth recovery immediately and recovers even while automatic retries were failing', async () => {
    vi.useFakeTimers()
    revalidateSession.mockRejectedValue(new Error('server still waking'))
    recoverSession.mockResolvedValue(undefined)
    invalidateQueries.mockResolvedValue(undefined)

    renderRecovery()
    dispatchPageShow(true)

    // Let the automatic reconnect exhaust its patient retries and surface the alert.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RESUME_RECONNECTING_GRACE_MS + totalTransientBackoff())
    })
    expect(screen.getByRole('alert')).toHaveTextContent('ComicPile could not reconnect')

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))

    // An explicit retry shows feedback immediately (no grace period) and recovers.
    expect(screen.getByRole('status')).toHaveTextContent('Reconnecting ComicPile')
    expect(recoverSession).toHaveBeenCalledWith(15000)
    expect(revalidateSession).toHaveBeenCalledTimes(RESUME_MAX_ATTEMPTS)

    await act(async () => {
      await Promise.resolve()
    })
    expect(invalidateQueries).toHaveBeenCalledOnce()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('does not allow automatic lifecycle events to supersede an explicit retry', async () => {
    vi.useFakeTimers()
    let finishExplicitRecovery: (() => void) | undefined
    revalidateSession.mockRejectedValue(axiosError(401))
    recoverSession.mockImplementation(
      () => new Promise<void>((resolve) => {
        finishExplicitRecovery = resolve
      }),
    )
    invalidateQueries.mockResolvedValue(undefined)

    renderRecovery()
    dispatchPageShow(true)
    await act(async () => {
      await Promise.resolve()
    })
    expect(screen.getByRole('alert')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(recoverSession).toHaveBeenCalledOnce()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100)
    })
    fireEvent(document, new Event('visibilitychange'))
    dispatchPageShow(true)
    expect(revalidateSession).toHaveBeenCalledTimes(1)

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
      await vi.advanceTimersByTimeAsync(RESUME_INITIAL_RETRY_DELAY_MS)
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
    await vi.waitFor(() => expect(invalidateQueries).toHaveBeenCalledOnce())

    now.mockReturnValue(11_001)
    fireEvent(document, new Event('visibilitychange'))
    await vi.waitFor(() => expect(revalidateSession).toHaveBeenCalledTimes(2))

    await act(async () => {
      finishFirstInvalidation?.()
    })

    await vi.waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  })
})
