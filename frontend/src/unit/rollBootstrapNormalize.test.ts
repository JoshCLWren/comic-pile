import { describe, expect, it } from 'vitest'
import { normalizeRollV2Bootstrap } from '../services/rollBootstrapNormalize'
import { makeRollV2Bootstrap, makeRollV2Item } from './rollV2BootstrapFixture'

describe('normalizeRollV2Bootstrap', () => {
  it('maps the single v2 response to session chrome and comic-first pool rows', () => {
    const item = makeRollV2Item({
      thread: { id: 9, title: 'Saga', format: 'Comic', last_activity_at: null },
      issue: {
        id: 909,
        number: '12',
        canonical_series_title: 'Saga (2012)',
        cover_url: 'https://images.example/saga-12.jpg',
      },
      identity: {
        source: 'comicvine',
        canonical_series_id: '42',
        state: 'confirmed',
        series_mapping_state: 'confirmed',
      },
      reader: {
        latest_rating: 5,
        average_rating: 4.25,
        rating_count: 4,
        read_count: 8,
        issue_count: 27,
        progress_scope: 'canonical_series_run',
      },
      routes: [{ kind: 'group', name: 'Earth-616 reading plan' }],
      overflow_routes_count: 2,
    })
    const state = normalizeRollV2Bootstrap(
      makeRollV2Bootstrap({
        session_id: 5,
        current_die: 20,
        pending_thread_id: 9,
        rollable: [item],
        snoozed_count: 1,
        blocked_count: 2,
        stale_thread_count: 3,
      }),
    )

    expect(state.session_id).toBe(5)
    expect(state.current_die).toBe(20)
    expect(state.pending_thread_id).toBe(9)
    expect(state.roll_pool).toHaveLength(1)
    expect(state.roll_pool[0]).toMatchObject({
      id: 9,
      title: 'Saga',
      format: 'Comic',
      issue_id: 909,
      issue_number: '12',
      cover_url: 'https://images.example/saga-12.jpg',
      canonical_series_title: 'Saga (2012)',
      identity_state: 'confirmed',
      series_mapping_state: 'confirmed',
      latest_rating: 5,
      average_rating: 4.25,
      rating_count: 4,
      read_count: 8,
      issue_count: 27,
      progress_scope: 'canonical_series_run',
      overflow_routes_count: 2,
    })
    expect(state.roll_pool[0]?.routes).toEqual([
      { kind: 'group', name: 'Earth-616 reading plan' },
    ])
  })

  it('keeps absent provider data null instead of inventing values', () => {
    const state = normalizeRollV2Bootstrap(
      makeRollV2Bootstrap({
        rollable: [
          makeRollV2Item({
            issue: {
              id: 5,
              number: '1',
              canonical_series_title: null,
              cover_url: null,
            },
            identity: {
              source: 'unavailable',
              canonical_series_id: null,
              state: 'unresolved',
              series_mapping_state: 'unresolved',
            },
            reader: {
              latest_rating: null,
              average_rating: null,
              rating_count: 0,
              read_count: 0,
              issue_count: null,
              progress_scope: 'thread',
            },
            routes: [],
          }),
        ],
      }),
    )

    expect(state.roll_pool[0]).toMatchObject({
      cover_url: null,
      canonical_series_title: null,
      identity_state: 'unresolved',
      latest_rating: null,
      average_rating: null,
      read_count: 0,
      issue_count: null,
      progress_scope: 'thread',
    })
    expect(state.roll_pool[0]?.routes).toEqual([])
  })

  it('maps a full d100 pool without dropping or reordering rows', () => {
    const items = Array.from({ length: 100 }, (_, index) =>
      makeRollV2Item({ thread: { id: index + 1, title: `Series ${index + 1}`, format: 'Comic' } }),
    )

    const state = normalizeRollV2Bootstrap(makeRollV2Bootstrap({ rollable: items, current_die: 100 }))

    expect(state.roll_pool).toHaveLength(100)
    expect(state.roll_pool[0]?.id).toBe(1)
    expect(state.roll_pool[99]?.id).toBe(100)
  })

  it('carries the bounded session summaries from the same v2 payload', () => {
    const state = normalizeRollV2Bootstrap(
      makeRollV2Bootstrap({
        snoozed_threads: [{ id: 3, title: 'Snoozed', format: 'Comic' }],
        snoozed_count: 4,
        skipped_thread_ids: [8],
        skipped_threads: [],
        blocked_count: 6,
        stale_thread_count: 1,
        stale_thread: { id: 7, title: 'Stale', format: 'Trade' },
        timezone: 'America/Chicago',
      }),
    )

    expect(state.snoozed_threads).toEqual([{ id: 3, title: 'Snoozed', format: 'Comic' }])
    expect(state.snoozed_count).toBe(4)
    expect(state.skipped_thread_ids).toEqual([8])
    expect(state.blocked_count).toBe(6)
    expect(state.stale_thread).toEqual({ id: 7, title: 'Stale', format: 'Trade' })
    expect(state.timezone).toBe('America/Chicago')
  })
})
