import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import ResumeRecovery from '../components/ResumeRecovery'

const { revalidateSession, recoverSession, invalidateSessionRecoveryCache, invalidateAfterResumeRecovery } = vi.hoisted(() => ({
  revalidateSession: vi.fn(),
  recoverSession: vi.fn(),
  invalidateSessionRecoveryCache: vi.fn(),
  invalidateAfterResumeRecovery: vi.fn(),
}))

vi.mock('../query/cacheEffects', () => ({
  invalidateSessionRecoveryCache,
  invalidateAfterResumeRecovery,
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
    <ResumeRecovery revalidateSession={revalidateSession} recoverSession={recoverSession}>
      <div>Last usable screen</div>
    </ResumeRecovery>,
  )
}

describe('ResumeRecovery', () => {
  beforeEach(() => {
    revalidateSession.mockReset()
    recoverSession.mockReset()
    invalidateSessionRecoveryCache.mockReset()
    invalidateAfterResumeRecovery.mockReset()
    setVisibilityState('visible')
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('revalidates auth and cached application data silently after a BFCache restore', async () => {
    revalidateSession.mockResolvedValue(undefined)
    invalidateAfterResumeRecovery.mockResolvedValue(undefined)

    renderRecovery()
    dispatchPageShow(true)

    expect(screen.getByText('Last usable screen')).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    await waitFor(() => expect(revalidateSession).toHaveBeenCalledWith(15000))
    // Scoped resume set (#2582): current session, roll bootstrap, queue
    // pages — never an unscoped invalidate of every query.
    await waitFor(() => expect(invalidateAfterResumeRecovery).toHaveBeenCalledOnce())
    expect(recoverSession).not.toHaveBeenCalled()
  })

  it('refreshes data without moving the viewport during resume recovery', async () => {
    // ResumeRecovery owns data/auth recovery, not viewport position (#2582):
    // the route restoration layer alone repositions the window.
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
    const scrollIntoView = vi
      .spyOn(Element.prototype, 'scrollIntoView')
      .mockImplementation(() => undefined)
    revalidateSession.mockResolvedValue(undefined)
    invalidateAfterResumeRecovery.mockResolvedValue(undefined)

    renderRecovery()
    dispatchPageShow(true)

    await waitFor(() => expect(revalidateSession).toHaveBeenCalledWith(15000))
    await waitFor(() => expect(invalidateAfterResumeRecovery).toHaveBeenCalled())
    expect(scrollTo).not.toHaveBeenCalled()
    expect(scrollIntoView).not.toHaveBeenCalled()
    scrollTo.mockRestore()
    scrollIntoView.mockRestore()
  })

  it('does not retry automatic resume after a definitive authentication failure', async () => {
    const unauthorized = Object.assign(new Error('unauthorized'), {
      isAxiosError: true,
      response: { status: 401 },
    })
    revalidateSession.mockRejectedValue(unauthorized)

    renderRecovery()
    dispatchPageShow(true)

    await waitFor(() => expect(revalidateSession).toHaveBeenCalledOnce())
    expect(revalidateSession).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('Last usable screen')).toBeInTheDocument()
  })

  it('keeps the application visible during automatic retries, then shows failure alert when retries are exhausted', async () => {
    vi.useFakeTimers()
    revalidateSession.mockRejectedValue(new Error('network suspended'))

    renderRecovery()
    dispatchPageShow(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })

    expect(revalidateSession).toHaveBeenCalledTimes(2)
    expect(screen.getByText('Last usable screen')).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('ComicPile could not reconnect')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
  })

  it('runs an explicit auth recovery immediately even inside the automatic throttle window', async () => {
    vi.useFakeTimers()
    const now = vi.spyOn(Date, 'now').mockReturnValue(10_000)
    revalidateSession.mockRejectedValue(new Error('server still waking'))
    recoverSession.mockResolvedValue(undefined)
    invalidateSessionRecoveryCache.mockResolvedValue(undefined)

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
    expect(invalidateAfterResumeRecovery).toHaveBeenCalledOnce()
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
    invalidateSessionRecoveryCache.mockResolvedValue(undefined)

    renderRecovery()
    dispatchPageShow(true)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(750)
    })

    expect(screen.getByRole('alert')).toHaveTextContent('ComicPile could not reconnect')
    expect(revalidateSession).toHaveBeenCalledTimes(2)

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

    expect(invalidateAfterResumeRecovery).toHaveBeenCalledOnce()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('ignores ordinary page shows and hidden tabs, then recovers on a visible resume with one successful retry', async () => {
    vi.useFakeTimers()
    revalidateSession
      .mockRejectedValueOnce(new Error('radio still waking'))
      .mockResolvedValueOnce(undefined)
    invalidateSessionRecoveryCache.mockResolvedValue(undefined)

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
    expect(invalidateAfterResumeRecovery).toHaveBeenCalledOnce()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('does not let an older invalidation hide a newer recovery attempt', async () => {
    let finishFirstInvalidation: (() => void) | undefined
    const now = vi.spyOn(Date, 'now').mockReturnValue(10_000)
    revalidateSession.mockResolvedValue(undefined)
    invalidateSessionRecoveryCache
      .mockImplementationOnce(
        () => new Promise<void>((resolve) => {
          finishFirstInvalidation = resolve
        }),
      )
      .mockResolvedValueOnce(undefined)

    renderRecovery()
    dispatchPageShow(true)
    await waitFor(() => expect(invalidateAfterResumeRecovery).toHaveBeenCalledOnce())

    now.mockReturnValue(11_001)
    fireEvent(document, new Event('visibilitychange'))
    await waitFor(() => expect(revalidateSession).toHaveBeenCalledTimes(2))

    await act(async () => {
      finishFirstInvalidation?.()
    })

    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  })
})
