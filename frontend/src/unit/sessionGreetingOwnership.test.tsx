import {
  renderHook,
  waitFor,
  type RenderHookOptions,
  type RenderHookResult,
} from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSession } from '../hooks/useSession'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import {
  resetSessionGreetingMemory,
  SESSION_STARTED_TOAST_MESSAGE,
  SESSION_STORAGE_KEY_PREFIX,
} from '../utils/sessionGreeting'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import type { ReactNode } from 'react'
import type { SessionApi } from '../services/apiTypes'
import type { RollBootstrapApi } from '../services/apiTypes'
import { cast } from '../utils/cast'
import { createToastSpy } from './toastSpy'
import { ToastContextSpy } from './toastTestHarness'

const sessionApiMock = vi.hoisted(() => ({
  getCurrent: vi.fn(),
}))
const rollBootstrapApiMock = vi.hoisted(() => ({ get: vi.fn() }))
// SAFETY: each mock implements only the hook surface these scenarios exercise,
// so the boundary coercion to the full API type is intentional.
const sessionApi = cast<SessionApi>(sessionApiMock)
const rollBootstrapApi = cast<RollBootstrapApi>(rollBootstrapApiMock)
const toast = createToastSpy()

const toastWrapper = ({ children }: { children: ReactNode }) => (
  <ToastContextSpy value={toast}>{children}</ToastContextSpy>
)

function renderHookWithToast<Result, Props>(
  render: (initialProps: Props) => Result,
  options?: RenderHookOptions<Props>,
): RenderHookResult<Result, Props> {
  return renderHook<Result, Props>(render, { ...options, wrapper: toastWrapper })
}

function bootstrapResponse(sessionId: number, userId: number): RollBootstrapResponse {
  return {
    session_id: sessionId,
    user_id: userId,
    current_die: 6,
    manual_die: null,
    pending_thread_id: null,
    last_rolled_result: null,
    session_mode: {
      active_bandwidth: null,
      predicted_bandwidth: null,
      bandwidth_confidence: null,
      bandwidth_source: null,
      bandwidth_version: null,
      active_intent: null,
      predicted_intent: null,
      intent_confidence: null,
      intent_source: null,
      intent_version: null,
      session_mode_correction_guidance: null,
    },
    active_thread: null,
    roll_pool: [],
    snoozed_threads: [],
    snoozed_count: 0,
    skipped_thread_ids: [],
    skipped_threads: [],
    blocked_count: 0,
    blocked_threads: [],
    stale_thread_count: 0,
    stale_thread: null,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetSessionGreetingMemory()
  sessionApiMock.getCurrent.mockResolvedValue({ id: 1, user_id: 1 })
  rollBootstrapApiMock.get.mockResolvedValue(bootstrapResponse(1, 1))
})

describe('session-started toast ownership across hooks', () => {
  it('emits exactly one toast when both hooks observe the same genuinely new session', async () => {
    localStorage.setItem(`${SESSION_STORAGE_KEY_PREFIX}_4`, '10')
    sessionApiMock.getCurrent.mockResolvedValue({ id: 12, user_id: 4 })
    rollBootstrapApiMock.get.mockResolvedValue(bootstrapResponse(12, 4))

    renderHookWithToast(() => {
      useSession(sessionApi)
      useRollBootstrap(rollBootstrapApi)
    })

    await waitFor(() => expect(toast.showToast).toHaveBeenCalledTimes(1))
    expect(toast.showToast).toHaveBeenCalledWith(SESSION_STARTED_TOAST_MESSAGE, 'info')
    expect(localStorage.getItem(`${SESSION_STORAGE_KEY_PREFIX}_4`)).toBe('12')
  })

  it('does not re-toast when navigating from the session surface to the Roll surface', async () => {
    localStorage.setItem(`${SESSION_STORAGE_KEY_PREFIX}_4`, '10')
    sessionApiMock.getCurrent.mockResolvedValue({ id: 12, user_id: 4 })
    rollBootstrapApiMock.get.mockResolvedValue(bootstrapResponse(12, 4))

    const session = renderHookWithToast(() => useSession(sessionApi))
    await waitFor(() => expect(toast.showToast).toHaveBeenCalledTimes(1))
    session.unmount()

    const roll = renderHookWithToast(() => useRollBootstrap(rollBootstrapApi))
    await waitFor(() => expect(roll.result.current.isPending).toBe(false))
    expect(toast.showToast).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(`${SESSION_STORAGE_KEY_PREFIX}_4`)).toBe('12')
  })

  it('does not re-toast when navigating from the Roll surface to the session surface', async () => {
    localStorage.setItem(`${SESSION_STORAGE_KEY_PREFIX}_4`, '10')
    sessionApiMock.getCurrent.mockResolvedValue({ id: 12, user_id: 4 })
    rollBootstrapApiMock.get.mockResolvedValue(bootstrapResponse(12, 4))

    const roll = renderHookWithToast(() => useRollBootstrap(rollBootstrapApi))
    await waitFor(() => expect(toast.showToast).toHaveBeenCalledTimes(1))
    roll.unmount()

    const session = renderHookWithToast(() => useSession(sessionApi))
    await waitFor(() => expect(session.result.current.isPending).toBe(false))
    await waitFor(() => expect(session.result.current.data?.id).toBe(12))
    expect(toast.showToast).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(`${SESSION_STORAGE_KEY_PREFIX}_4`)).toBe('12')
  })

  it('never toasts for a first session while navigating between surfaces', async () => {
    sessionApiMock.getCurrent.mockResolvedValue({ id: 12, user_id: 4 })
    rollBootstrapApiMock.get.mockResolvedValue(bootstrapResponse(12, 4))

    const roll = renderHookWithToast(() => useRollBootstrap(rollBootstrapApi))
    await waitFor(() => expect(roll.result.current.isPending).toBe(false))
    expect(toast.showToast).not.toHaveBeenCalled()
    roll.unmount()

    const session = renderHookWithToast(() => useSession(sessionApi))
    await waitFor(() => expect(session.result.current.data?.id).toBe(12))
    expect(toast.showToast).not.toHaveBeenCalled()
    expect(localStorage.getItem(`${SESSION_STORAGE_KEY_PREFIX}_4`)).toBe('12')
  })

  it('does not crash or toast for simultaneous consumers when storage is unavailable', async () => {
    const originalStorage = window.localStorage
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: vi.fn(() => {
          throw new Error('storage unavailable')
        }),
        setItem: vi.fn(() => {
          throw new Error('storage unavailable')
        }),
        removeItem: vi.fn(),
        clear: vi.fn(),
      },
    })
    try {
      sessionApiMock.getCurrent.mockResolvedValue({ id: 12, user_id: 4 })
      rollBootstrapApiMock.get.mockResolvedValue(bootstrapResponse(12, 4))

      const view = renderHookWithToast(() => {
        const session = useSession(sessionApi)
        const roll = useRollBootstrap(rollBootstrapApi)
        return { session, roll }
      })

      await waitFor(() => {
        expect(view.result.current.session.isPending).toBe(false)
        expect(view.result.current.roll.isPending).toBe(false)
      })
      expect(toast.showToast).not.toHaveBeenCalled()
    } finally {
      Object.defineProperty(window, 'localStorage', {
        configurable: true,
        value: originalStorage,
      })
    }
  })

  it('does not duplicate the toast for simultaneous consumers when the storage write fails', async () => {
    const originalStorage = window.localStorage
    const store = new Map([[`${SESSION_STORAGE_KEY_PREFIX}_4`, '10']])
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: vi.fn((key: string) => store.get(key) ?? null),
        setItem: vi.fn(() => {
          throw new Error('storage unavailable')
        }),
        removeItem: vi.fn(),
        clear: vi.fn(),
      },
    })
    try {
      sessionApiMock.getCurrent.mockResolvedValue({ id: 12, user_id: 4 })
      rollBootstrapApiMock.get.mockResolvedValue(bootstrapResponse(12, 4))

      renderHookWithToast(() => {
        useSession(sessionApi)
        useRollBootstrap(rollBootstrapApi)
      })

      await waitFor(() => expect(toast.showToast).toHaveBeenCalledTimes(1))
      expect(toast.showToast).toHaveBeenCalledWith(SESSION_STARTED_TOAST_MESSAGE, 'info')
    } finally {
      Object.defineProperty(window, 'localStorage', {
        configurable: true,
        value: originalStorage,
      })
    }
  })
})
