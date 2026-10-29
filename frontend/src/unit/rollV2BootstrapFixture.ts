import type { SessionMode } from '../types'
import type {
  RollV2BootstrapResponse,
  RollV2Item,
  RollV2Reader,
  RollV2Thread,
  RollV2Issue,
  RollV2Identity,
  RollV2Route,
} from '../types/rollV2'

const SESSION_MODE: SessionMode = {
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
}

/**
 * Build one v2 rollable item for tests.
 *
 * Overrides are shallow per nested object so a test only states the field it
 * exercises and every other value keeps an honest, non-invented default.
 *
 * @param overrides - Fields to replace on the default item.
 * @returns A complete v2 rollable item.
 */
export function makeRollV2Item(overrides: Partial<RollV2Item> = {}): RollV2Item {
  const thread: RollV2Thread = {
    id: 1,
    title: 'Saga',
    format: 'Comic',
    last_activity_at: '2026-01-02T00:00:00Z',
    ...overrides.thread,
  }
  const issue: RollV2Issue = {
    id: 101,
    number: '3',
    canonical_series_title: 'Saga',
    cover_url: 'https://images.example/saga-3.jpg',
    ...overrides.issue,
  }
  const identity: RollV2Identity = {
    source: 'comicvine',
    canonical_series_id: '42',
    state: 'confirmed',
    series_mapping_state: 'confirmed',
    ...overrides.identity,
  }
  const reader: RollV2Reader = {
    latest_rating: 4.5,
    average_rating: 4.1,
    rating_count: 7,
    read_count: 8,
    issue_count: 27,
    progress_scope: 'canonical_series_run',
    ...overrides.reader,
  }
  const routes: RollV2Route[] = overrides.routes ?? [{ kind: 'group', name: 'Earth-616 reading plan' }]

  return {
    thread,
    issue,
    identity,
    reader,
    routes,
    overflow_routes_count: overrides.overflow_routes_count ?? 0,
  }
}

/**
 * Build an authoritative v2 bootstrap payload for tests.
 *
 * @param overrides - Fields to replace on the empty bootstrap payload.
 * @returns A complete `RollV2BootstrapResponse`.
 */
export function makeRollV2Bootstrap(
  overrides: Partial<RollV2BootstrapResponse> = {},
): RollV2BootstrapResponse {
  return {
    session_id: 11,
    user_id: 7,
    current_die: 6,
    manual_die: null,
    pending_thread_id: null,
    last_rolled_result: null,
    session_mode: SESSION_MODE,
    active_thread: null,
    roll_recovery: null,
    bandwidth: {
      predicted_bandwidth: null,
      active_bandwidth: null,
      confidence: null,
      source: null,
      mode_version: null,
    },
    rollable: [],
    last_read: null,
    snoozed_threads: [],
    snoozed_count: 0,
    skipped_thread_ids: [],
    skipped_threads: [],
    blocked_count: 0,
    blocked_threads: [],
    stale_thread_count: 0,
    stale_thread: null,
    timezone: null,
    ...overrides,
  }
}
