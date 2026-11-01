import { describe, expect, it } from 'vitest'
import { adaptRollV2Bootstrap } from '../services/adaptRollV2Bootstrap'
import type { RollV2BootstrapResponse } from '../types/rollV2'

// SAFETY: The adapter accesses only the populated fields in this partial
// fixture; omitted fields are not involved in the assertions below.
const sample = {
  session_id: 17,
  user_id: 1,
  rollable: [{
    thread: {
      id: 101, title: 'Tagged comic', format: 'Comic',
      tags: [{
        id: 1, name: 'Favorites', normalized_name: 'favorites',
        scope: 'global', owner_user_id: null, color: '#336699',
        created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
      }],
    },
    issue: { id: 404, number: '12' },
    routes: [{ kind: 'group', name: 'Reading list' }],
  }],
// SAFETY: This intentionally partial v2 fixture covers only the adapter's
// relevant runtime invariants; unused session fields are never inspected.
} as RollV2BootstrapResponse

describe('native v2 Roll bootstrap compatibility', () => {
  it('retains die-face tags, exact issue and route labels without diagnostic reports', () => {
    const state = adaptRollV2Bootstrap(sample)
    expect(state.roll_pool[0].tags?.map(tag => tag.name)).toEqual(['Favorites'])
    expect(state.roll_pool[0].issue_id).toBe(404)
    expect(state.roll_pool[0].issue_number).toBe('12')
    expect(state.roll_pool[0].route_labels).toEqual(['Reading list'])
    for (const diagnostic of ['blocked_count', 'stale_thread_count', 'inactive_count', 'excluded_count']) {
      expect(state).not.toHaveProperty(diagnostic)
    }
  })

  it('fails closed when the native response omits rollable candidates', () => {
    const { rollable: _ignored, ...incomplete } = sample
    // SAFETY: deliberately incomplete fixture exercises the adapter's runtime guard.
    expect(() => adaptRollV2Bootstrap(incomplete as RollV2BootstrapResponse))
      .toThrow('Incomplete native Roll v2 bootstrap response')
  })

  it('refuses native candidate rows without visible tags', () => {
    const withoutTags = {
      ...sample,
      rollable: [{ ...sample.rollable[0], thread: { id: 101, title: 'No tags', format: 'Comic' } }],
    }
    // SAFETY: This deliberately malformed candidate must fail at the adapter boundary.
    expect(() => adaptRollV2Bootstrap(withoutTags as RollV2BootstrapResponse))
      .toThrow('Incomplete native Roll v2 candidate')
  })
})
