import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cast } from '../utils/cast'
import {
  isAmbiguousNetworkFailure,
  publishRollState,
  reconcileAmbiguousRollMutation,
  ROLL_STATE_RECONCILED_EVENT,
} from '../hooks/rollMutationReconciliation'
import { rollStateApi } from '../services/rollStateApi'
import type { RollState } from '../types/rollState'

vi.mock('../services/rollStateApi', () => ({
  rollStateApi: {
    get: vi.fn(),
  },
}))

const mockedBootstrap = vi.mocked(rollStateApi.get)
const bootstrapState = (
  sessionId: number,
  pendingThreadId: number | null,
): RollState => ({
  pending_thread_id: pendingThreadId,
  last_rolled_result: pendingThreadId === null ? null : 1,
  active_thread: null,
  roll_pool: [],
  snoozed_threads: [],
  snoozed_count: 0,
})

beforeEach(() => {
  mockedBootstrap.mockReset()
  localStorage.clear()
})

describe('Roll mutation reconciliation', () => {
  it('classifies only response-less timeout and network failures as ambiguous', () => {
    expect(isAmbiguousNetworkFailure(null)).toBe(false)
    expect(isAmbiguousNetworkFailure('timeout')).toBe(false)
    expect(isAmbiguousNetworkFailure({ response: { status: 500 }, code: 'ECONNABORTED' })).toBe(false)
    expect(isAmbiguousNetworkFailure({ code: 'ECONNABORTED' })).toBe(true)
    expect(isAmbiguousNetworkFailure({ code: 'ETIMEDOUT' })).toBe(true)
    expect(isAmbiguousNetworkFailure(new Error('request timeout'))).toBe(true)
    expect(isAmbiguousNetworkFailure(new Error('Network Error'))).toBe(true)
    expect(isAmbiguousNetworkFailure(new Error('ordinary failure'))).toBe(false)
  })

  it('distinguishes committed and still-pending mutations with and without an expected thread', async () => {
    mockedBootstrap
      .mockResolvedValueOnce(bootstrapState(12, null))
      .mockResolvedValueOnce(bootstrapState(12, 7))
      .mockResolvedValueOnce(bootstrapState(12, 7))
      .mockResolvedValueOnce(bootstrapState(12, 9))
      .mockResolvedValueOnce({
        ...bootstrapState(12, null),
        pending_thread_id: cast<number>('invalid'),
      })

    await expect(reconcileAmbiguousRollMutation()).resolves.toMatchObject({ committed: true })
    await expect(reconcileAmbiguousRollMutation()).resolves.toMatchObject({ committed: false })
    await expect(reconcileAmbiguousRollMutation(7)).resolves.toMatchObject({ committed: false })
    await expect(reconcileAmbiguousRollMutation(7)).resolves.toMatchObject({ committed: true })
    await expect(reconcileAmbiguousRollMutation()).resolves.toMatchObject({ committed: true })
    expect(mockedBootstrap).toHaveBeenCalledTimes(5)
  })

  it('does not publish when the browser CustomEvent API is unavailable', () => {
    const reconciled = vi.fn()
    window.addEventListener(ROLL_STATE_RECONCILED_EVENT, reconciled)
    vi.stubGlobal('CustomEvent', undefined)

    try {
      publishRollState(bootstrapState(8, null))
      expect(reconciled).not.toHaveBeenCalled()
    } finally {
      vi.unstubAllGlobals()
      window.removeEventListener(ROLL_STATE_RECONCILED_EVENT, reconciled)
    }
  })

})
