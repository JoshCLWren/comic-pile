import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ResumeRecovery from '../components/ResumeRecovery'

const { revalidateSession, invalidateQueries } = vi.hoisted(() => ({
  revalidateSession: vi.fn(),
  invalidateQueries: vi.fn(),
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

function renderRecovery() {
  return render(
    <ResumeRecovery revalidateSession={revalidateSession}>
      <div>Last usable screen</div>
    </ResumeRecovery>,
  )
}

describe('ResumeRecovery', () => {
  beforeEach(() => {
    revalidateSession.mockReset()
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
    await waitFor(() => expect(revalidateSession).toHaveBeenCalledWith(8000))
    await waitFor(() => expect(invalidateQueries).toHaveBeenCalledOnce())
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
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
})
