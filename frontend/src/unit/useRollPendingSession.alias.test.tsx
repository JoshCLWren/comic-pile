/**
 * Pending Roll recovery must keep both numbers of a dual-numbered comic (#4652).
 */
import { renderHook } from '@testing-library/react'
import { useRollPageState } from '../pages/RollPage/useRollPageState'
import { useRollPendingSession } from '../pages/RollPage/useRollPendingSession'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

function useHydratedRoll(bootstrap: RollBootstrapResponse) {
  const state = useRollPageState()
  useRollPendingSession({ state, bootstrap, rollPool: [] })
  return state
}

function pendingBootstrap(): RollBootstrapResponse {
  return {
    session_id: 1,
    user_id: 1,
    pending_thread_id: 404,
    last_rolled_result: null,
    // SAFETY: recovery hydration only reads the pending id and active thread, never session mode.
    session_mode: {} as RollBootstrapResponse['session_mode'],
    active_thread: {
      id: 404,
      title: 'Saga',
      format: 'Comic',
      issues_remaining: 5,
      queue_position: 1,
      issue_id: 77,
      issue_number: '3',
      issue_number_alias: '100',
      provider_issue_number: '101',
      next_issue_id: 77,
      next_issue_number: '3',
    },
    roll_pool: [],
    snoozed_threads: [],
    snoozed_count: 0,
    skipped_thread_ids: [],
    skipped_threads: [],
  }
}

describe('pending Roll alias hydration (#4652)', () => {
  it('restores the authored, alternate and provider numbers from bootstrap', () => {
    const { result } = renderHook(() => useHydratedRoll(pendingBootstrap()))

    expect(result.current.activeRatingThread).toMatchObject({
      id: 404,
      issue_number: '3',
      issue_number_alias: '100',
      provider_issue_number: '101',
    })
  })
})
