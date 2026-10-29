import { renderHook } from '@testing-library/react'
import type { NavigateFunction } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { useRollBootstrapSync } from '../pages/RollPage/useRollBootstrapSync'
import { useRollPageState } from '../pages/RollPage/useRollPageState'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import { cast } from '../utils/cast'

/**
 * Die-mode persistence regression coverage for #4279.
 *
 * Navigation is what re-mounts the Roll page, so each case renders the hook
 * with the bootstrap snapshot the server hands Roll after that navigation:
 *
 * - Queue -> Roll: the queue invalidates the bootstrap, so Roll mounts with a
 *   freshly fetched snapshot.
 * - Glossary -> Roll: Roll mounts with the still-cached snapshot.
 *
 * Both paths must project the same die mode, and a cleared manual override must
 * project the automatic die the server reports.
 */
function bootstrapWithDieModes(
  currentDie: number,
  manualDie: number | null,
): RollBootstrapResponse {
  return {
    session_id: 1,
    user_id: 1,
    current_die: currentDie,
    manual_die: manualDie,
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

const navigate = cast<NavigateFunction>(vi.fn())

function renderDieModeSync(bootstrap: RollBootstrapResponse | null) {
  return renderHook(
    ({ snapshot }: { snapshot: RollBootstrapResponse | null }) => {
      const state = useRollPageState()
      useRollBootstrapSync({
        state,
        bootstrap: snapshot,
        isBootstrapError: false,
        bootstrapError: null,
        navigate,
      })
      return state
    },
    { initialProps: { snapshot: bootstrap } },
  )
}

describe('Roll die-mode sync across navigation (#4279)', () => {
  it('restores the pinned manual die on a fresh Queue -> Roll snapshot', () => {
    const { result } = renderDieModeSync(bootstrapWithDieModes(20, 20))

    expect(result.current.currentDie).toBe(20)
  })

  it('restores the pinned manual die when Roll re-mounts from the Glossary cache', () => {
    const cached = bootstrapWithDieModes(20, 20)
    const first = renderDieModeSync(cached)
    expect(first.result.current.currentDie).toBe(20)
    first.unmount()

    const second = renderDieModeSync(cached)

    expect(second.result.current.currentDie).toBe(20)
  })

  it('prefers manual_die over a separately reported automatic current_die', () => {
    const { result } = renderDieModeSync(bootstrapWithDieModes(8, 20))

    expect(result.current.currentDie).toBe(20)
  })

  it('applies the automatic die once the server reports the override cleared', () => {
    const { result, rerender } = renderDieModeSync(bootstrapWithDieModes(20, 20))
    expect(result.current.currentDie).toBe(20)

    rerender({ snapshot: bootstrapWithDieModes(8, null) })

    expect(result.current.currentDie).toBe(8)
  })
})
