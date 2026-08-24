import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { resolveBrowserTimezone, useRollBootstrap } from '../hooks/useRollBootstrap'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import { ToastProvider } from '../contexts/ToastProvider'

vi.mock('../services/rollBootstrapApi', () => ({
  rollBootstrapApi: {
    get: vi.fn(),
  },
}))

const mockedBootstrap = vi.mocked(rollBootstrapApi.get)

const bootstrapResponse = {
  session_id: 1,
  user_id: 1,
  current_die: 6,
  manual_die: null,
  pending_thread_id: null,
  last_rolled_result: null,
  active_thread: null,
  roll_pool: [],
  snoozed_threads: [],
  snoozed_count: 0,
  blocked_count: 0,
  blocked_threads: [],
  stale_thread_count: 0,
  stale_thread: null,
} as RollBootstrapResponse

function renderBootstrap() {
  return renderHook(() => useRollBootstrap(), {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <ToastProvider>{children}</ToastProvider>
    ),
  })
}

beforeEach(() => {
  mockedBootstrap.mockReset()
})

it('captures the browser-resolved timezone on the initial bootstrap fetch', async () => {
  mockedBootstrap.mockResolvedValue(bootstrapResponse)

  const { result } = renderBootstrap()

  await waitFor(() => expect(result.current.isPending).toBe(false))
  expect(result.current.data).toBe(bootstrapResponse)

  const expectedTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone
  expect(mockedBootstrap).toHaveBeenCalledWith(expectedTimezone)
})

it('resolves to undefined when the browser cannot resolve a timezone', () => {
  const originalDateTimeFormat = Intl.DateTimeFormat
  const brokenIntl = {
    ...Intl,
    DateTimeFormat: (() => {
      throw new Error('Intl unavailable')
    }) as unknown as typeof Intl.DateTimeFormat,
  }
  Object.defineProperty(globalThis, 'Intl', {
    configurable: true,
    writable: true,
    value: brokenIntl,
  })

  try {
    expect(resolveBrowserTimezone()).toBeUndefined()
  } finally {
    Object.defineProperty(globalThis, 'Intl', {
      configurable: true,
      writable: true,
      value: { ...brokenIntl, DateTimeFormat: originalDateTimeFormat },
    })
  }
})
