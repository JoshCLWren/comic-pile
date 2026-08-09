import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  isAuthenticationMutationFailure,
  recoverProtectedRollMutation,
} from '../hooks/rollMutationReconciliation'
import { protectedRollMutationApi } from '../services/protectedRollMutationApi'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

vi.mock('../services/protectedRollMutationApi', () => ({
  protectedRollMutationApi: {
    bootstrap: vi.fn(),
  },
}))

const mockedProtectedApi = vi.mocked(protectedRollMutationApi)

function bootstrapState(pendingThreadId: number | null): RollBootstrapResponse {
  return {
    session_id: 1,
    user_id: 1,
    current_die: 6,
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
  }
}

const authFailure = {
  response: { status: 403, data: { detail: 'Not authenticated' } },
}

describe('protected Roll mutation recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('recognizes only authentication-shaped mutation failures', () => {
    expect(isAuthenticationMutationFailure({ response: { status: 401 } })).toBe(true)
    expect(isAuthenticationMutationFailure(authFailure)).toBe(true)
    expect(isAuthenticationMutationFailure({ response: { status: 403, data: { detail: 'Forbidden' } } })).toBe(false)
    expect(isAuthenticationMutationFailure({ response: { status: 500 } })).toBe(false)
  })

  it('waits through recoverable auth failures then retries the same pending mutation once', async () => {
    mockedProtectedApi.bootstrap
      .mockRejectedValueOnce(authFailure)
      .mockRejectedValueOnce(authFailure)
      .mockResolvedValueOnce(bootstrapState(7))
    const retry = vi.fn().mockResolvedValue(undefined)
    const wait = vi.fn().mockResolvedValue(undefined)

    await expect(recoverProtectedRollMutation(7, retry, wait)).resolves.toEqual({
      status: 'retried',
      value: undefined,
    })

    expect(mockedProtectedApi.bootstrap).toHaveBeenCalledTimes(3)
    expect(wait).toHaveBeenCalledTimes(2)
    expect(retry).toHaveBeenCalledTimes(1)
  })

  it('refuses to replay after authoritative pending state advances', async () => {
    mockedProtectedApi.bootstrap.mockResolvedValueOnce(bootstrapState(9))
    const retry = vi.fn()

    await expect(recoverProtectedRollMutation(7, retry, vi.fn())).resolves.toEqual({
      status: 'stale',
    })

    expect(retry).not.toHaveBeenCalled()
  })

  it('surfaces a definitive recovery failure without replaying', async () => {
    const revoked = { response: { status: 403, data: { detail: 'Revoked token' } } }
    mockedProtectedApi.bootstrap.mockRejectedValueOnce(revoked)
    const retry = vi.fn()

    await expect(recoverProtectedRollMutation(7, retry, vi.fn())).rejects.toBe(revoked)
    expect(retry).not.toHaveBeenCalled()
  })
})
