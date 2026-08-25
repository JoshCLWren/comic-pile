import { renderHookWithClient } from './queryTestWrapper'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { ToastProvider } from '../contexts/ToastProvider'
import { it, expect, vi, beforeEach } from 'vitest'
import { rollBootstrapApi } from '../services/rollBootstrapApi'

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
} as any

beforeEach(() => {
  mockedBootstrap.mockReset()
  localStorage.clear()
})

it('debug', async () => {
  mockedBootstrap.mockResolvedValue(bootstrapResponse)
  const { result } = renderHookWithClient(() => useRollBootstrap(), {
    innerWrapper: ({ children }) => <ToastProvider>{children}</ToastProvider>
  })
  console.log('result:', result)
  console.log('result.current:', result.current)
  console.log('result.error:', result.error)
  expect(result.current).toBeDefined()
})
