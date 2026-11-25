import { act, fireEvent, render, renderHook, screen } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes, useNavigate } from 'react-router-dom'
import type { ReactElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useKeepalive } from '../hooks/useKeepalive'

// Regression coverage for the review fixes in PR #4068 (issue #3480): the
// keepalive call must go to the corrected relative URL (never baking the
// axios `/api` baseURL into the hook's path), the heartbeat must survive
// route changes, and it must restart after idle or a long-hidden tab while
// never keeping Neon warm when the tab is hidden or the user is idle.

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }))
vi.mock('../services/api', () => ({ default: { get: apiGet } }))

const KEEPALIVE_INTERVAL_MS = 4 * 60 * 1000
const PREWARM_DEBOUNCE_MS = 1000

let debugSpy: ReturnType<typeof vi.spyOn>

function setTabHidden(hidden: boolean): void {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
  document.dispatchEvent(new Event('visibilitychange'))
}

function setTabHiddenSilently(hidden: boolean): void {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
}

function userActivity(type: 'keydown' | 'mousemove' | 'scroll' = 'keydown'): void {
  document.dispatchEvent(new Event(type))
}

async function advanceTime(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

function WarmShell(): ReactElement {
  useKeepalive(true)
  return (
    <>
      <Outlet />
    </>
  )
}

function CrossingRouteButton(): ReactElement {
  const navigate = useNavigate()
  return (
    <button type="button" onClick={() => navigate('/sessions')}>
      navigate
    </button>
  )
}

function renderWarmShellAcrossRoutes() {
  return render(
    <MemoryRouter initialEntries={['/queue']}>
      <Routes>
        <Route path="/" element={<WarmShell />}>
          <Route path="queue" element={<CrossingRouteButton />} />
          <Route path="sessions" element={<div>sessions body</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.useFakeTimers()
  apiGet.mockReset()
  apiGet.mockResolvedValue(undefined)
  setTabHiddenSilently(false)
  debugSpy = vi.spyOn(console, 'debug')
  debugSpy.mockImplementation(() => {})
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useKeepalive', () => {
  it('prewarms the corrected relative keepalive URL on app open', () => {
    const { unmount } = renderHook(() => useKeepalive())

    expect(apiGet).toHaveBeenCalledTimes(1)
    expect(apiGet.mock.calls[0]?.[0]).toBe('/v1/keepalive')
    // Regression: the hook must pass a path relative to the axios `/api`
    // baseURL; a leading `/api` here duplicated the prefix in production.
    expect(String(apiGet.mock.calls[0]?.[0]).startsWith('/api')).toBe(false)
    expect(apiGet.mock.calls[0]?.[1]).toEqual({ timeout: 5000 })

    unmount()
  })

  it('keeps the heartbeat alive across route changes without losing or duplicating pings', async () => {
    renderWarmShellAcrossRoutes()

    expect(apiGet).toHaveBeenCalledTimes(1)

    await advanceTime(KEEPALIVE_INTERVAL_MS)
    expect(apiGet).toHaveBeenCalledTimes(2)

    // Continued interaction on the next screen refreshes the activity window.
    userActivity()
    await advanceTime(KEEPALIVE_INTERVAL_MS / 2)
    expect(apiGet).toHaveBeenCalledTimes(2)

    fireEvent.click(screen.getByRole('button', { name: /navigate/i }))

    await advanceTime(KEEPALIVE_INTERVAL_MS / 2)
    expect(apiGet).toHaveBeenCalledTimes(3)
  })

  it('collapses rapid visibility flapping into one debounced prewarm and one interval', async () => {
    renderHook(() => useKeepalive())
    expect(apiGet).toHaveBeenCalledTimes(1)

    setTabHidden(true)
    setTabHidden(false)
    setTabHidden(true)
    setTabHidden(false)
    setTabHidden(false)

    await advanceTime(PREWARM_DEBOUNCE_MS + 5)
    expect(apiGet).toHaveBeenCalledTimes(2)

    // A visibility event while still visible reschedules cleanly and the
    // already-running interval is not started a second time.
    setTabHiddenSilently(false)
    document.dispatchEvent(new Event('visibilitychange'))
    await advanceTime(PREWARM_DEBOUNCE_MS + 5)
    expect(apiGet).toHaveBeenCalledTimes(3)

    await advanceTime(KEEPALIVE_INTERVAL_MS)
    expect(apiGet).toHaveBeenCalledTimes(4)
  })

  it('stops warming while the tab is hidden and restarts after it returns', async () => {
    renderHook(() => useKeepalive())
    expect(apiGet).toHaveBeenCalledTimes(1)

    setTabHidden(true)
    await advanceTime(KEEPALIVE_INTERVAL_MS * 3)
    expect(apiGet).toHaveBeenCalledTimes(1)

    // A long-hidden tab return treats being visible again as fresh activity:
    // an immediate debounced prewarm plus a resumed heartbeat.
    setTabHidden(false)
    await advanceTime(PREWARM_DEBOUNCE_MS + 5)
    expect(apiGet).toHaveBeenCalledTimes(2)

    await advanceTime(KEEPALIVE_INTERVAL_MS)
    expect(apiGet).toHaveBeenCalledTimes(3)
  })

  it('stops when the user goes idle and restarts on the next activity burst', async () => {
    renderHook(() => useKeepalive())
    expect(apiGet).toHaveBeenCalledTimes(1)

    await advanceTime(KEEPALIVE_INTERVAL_MS)
    expect(apiGet).toHaveBeenCalledTimes(2)

    // No activity since mount: the next tick is already past the idle window
    // and stops the interval instead of pinging.
    await advanceTime(KEEPALIVE_INTERVAL_MS)
    expect(apiGet).toHaveBeenCalledTimes(2)

    userActivity()
    expect(apiGet).toHaveBeenCalledTimes(3)

    // Activity while the interval already restarted triggers no extra prewarm.
    userActivity()
    expect(apiGet).toHaveBeenCalledTimes(3)

    await advanceTime(KEEPALIVE_INTERVAL_MS)
    expect(apiGet).toHaveBeenCalledTimes(4)
  })

  it('never restarts or pings from activity while the tab is hidden', async () => {
    renderHook(() => useKeepalive())
    expect(apiGet).toHaveBeenCalledTimes(1)

    setTabHidden(true)
    userActivity('mousemove')
    userActivity('keydown')
    await advanceTime(KEEPALIVE_INTERVAL_MS)

    expect(apiGet).toHaveBeenCalledTimes(1)
  })

  it('fails silently and keeps the heartbeat running', async () => {
    renderHook(() => useKeepalive())
    expect(apiGet).toHaveBeenCalledTimes(1)

    apiGet.mockRejectedValueOnce(new Error('keepalive failed'))

    await advanceTime(KEEPALIVE_INTERVAL_MS)
    expect(apiGet).toHaveBeenCalledTimes(2)

    // Continued activity after the failed probe keeps the window active so the
    // next heartbeat still runs, proving the failure never broke the hook.
    userActivity()

    await advanceTime(KEEPALIVE_INTERVAL_MS)
    expect(apiGet).toHaveBeenCalledTimes(3)

    expect(debugSpy).toHaveBeenCalledWith('Keepalive ping failed:', expect.anything())
  })

  it('skips a second prewarm while one is already in flight', async () => {
    apiGet.mockImplementationOnce(() => new Promise(() => {}))

    renderHook(() => useKeepalive())
    expect(apiGet).toHaveBeenCalledTimes(1)

    setTabHidden(true)
    setTabHidden(false)
    await advanceTime(PREWARM_DEBOUNCE_MS + 5)

    expect(apiGet).toHaveBeenCalledTimes(1)
  })

  it('exposes transient warming state while a heartbeat is in flight', async () => {
    let release: (() => void) | undefined
    // The mount prewarm resolves normally; the pending in-flight request we
    // observe is the next heartbeat tick.
    apiGet.mockResolvedValueOnce(undefined)
    apiGet.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          release = resolve
        }),
    )

    const hook = renderHook(() => useKeepalive())
    expect(apiGet).toHaveBeenCalledTimes(1)

    await advanceTime(KEEPALIVE_INTERVAL_MS)
    expect(apiGet).toHaveBeenCalledTimes(2)
    expect(hook.result.current.isWarming).toBe(true)

    await act(async () => {
      release?.()
    })
    expect(hook.result.current.isWarming).toBe(false)
  })

  it('does not run any keepalive while disabled', async () => {
    renderHook(() => useKeepalive(false))

    await advanceTime(KEEPALIVE_INTERVAL_MS * 3)
    userActivity()
    await advanceTime(KEEPALIVE_INTERVAL_MS)

    expect(apiGet).not.toHaveBeenCalled()
  })

  it('does not prewarm when the app opens with the tab already hidden', async () => {
    setTabHiddenSilently(true)
    renderHook(() => useKeepalive())

    await advanceTime(KEEPALIVE_INTERVAL_MS * 2)
    userActivity()
    await advanceTime(KEEPALIVE_INTERVAL_MS)

    expect(apiGet).not.toHaveBeenCalled()
  })

  it('clears the heartbeat and pending prewarm on unmount', async () => {
    const hook = renderHook(() => useKeepalive())
    expect(apiGet).toHaveBeenCalledTimes(1)

    setTabHidden(true)
    setTabHidden(false)
    hook.unmount()

    await advanceTime(PREWARM_DEBOUNCE_MS + KEEPALIVE_INTERVAL_MS)
    userActivity()
    await advanceTime(KEEPALIVE_INTERVAL_MS)

    expect(apiGet).toHaveBeenCalledTimes(1)
  })
})
