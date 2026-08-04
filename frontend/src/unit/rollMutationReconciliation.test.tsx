import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import { publishRollBootstrap } from '../hooks/rollMutationReconciliation'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

vi.mock('../services/rollBootstrapApi', () => ({
  rollBootstrapApi: {
    get: vi.fn(),
  },
}))

const mockedBootstrap = vi.mocked(rollBootstrapApi.get)

const bootstrapState = (
  currentDie: RollBootstrapResponse['current_die'],
  pendingThreadId: number | null,
): RollBootstrapResponse => ({
  session_id: 1,
  user_id: 1,
  current_die: currentDie,
  manual_die: null,
  pending_thread_id: pendingThreadId,
  last_rolled_result: pendingThreadId === null ? null : 1,
  active_thread: null,
  roll_pool: [],
  snoozed_threads: [],
  snoozed_count: 0,
  blocked_count: 0,
  blocked_threads: [],
  stale_thread_count: 0,
  stale_thread: null,
})

beforeEach(() => {
  mockedBootstrap.mockReset()
  localStorage.clear()
})

it('replaces mounted Roll bootstrap state when a mutation publishes reconciliation', async () => {
  const initial = bootstrapState(6, 7)
  const reconciled = bootstrapState(8, null)
  mockedBootstrap.mockResolvedValue(initial)

  const { result } = renderHook(() => useRollBootstrap(), {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <ToastProvider>{children}</ToastProvider>
    ),
  })

  await waitFor(() => expect(result.current.data).toBe(initial))

  act(() => {
    publishRollBootstrap(reconciled)
  })

  expect(result.current.data).toBe(reconciled)
  expect(result.current.data?.current_die).toBe(8)
  expect(result.current.data?.pending_thread_id).toBeNull()
  expect(result.current.isPending).toBe(false)
  expect(result.current.isError).toBe(false)
  expect(result.current.error).toBeNull()
})
