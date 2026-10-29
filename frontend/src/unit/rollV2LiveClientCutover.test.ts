import { beforeEach, expect, it } from 'vitest'
import { createRollBootstrapApi } from '../services/rollBootstrapApi'
import { createProtectedRollMutationApi } from '../services/protectedRollMutationApi'
import { createHttpClientStub } from './httpClientStub'
import type { RollV2BootstrapResponse } from '../types/rollV2'

const client = createHttpClientStub()
const rollBootstrap = createRollBootstrapApi(client)
const protectedMutations = createProtectedRollMutationApi(client)

const nativeResponse: RollV2BootstrapResponse = {
  session_id: 23,
  user_id: 1,
  current_die: 6,
  manual_die: null,
  pending_thread_id: 7,
  last_rolled_result: 2,
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
  roll_recovery: null,
  bandwidth: {
    predicted_bandwidth: null,
    active_bandwidth: null,
    confidence: null,
    source: null,
    mode_version: null,
  },
  rollable: [{
    thread: { id: 7, title: 'The Good Comics', format: 'comic', last_activity_at: null },
    issue: { id: 91, number: '4', canonical_series_title: 'The Good Comics', cover_url: null },
    identity: {
      source: 'comicvine',
      canonical_series_id: '123',
      state: 'confirmed',
      series_mapping_state: 'confirmed',
    },
    reader: {
      latest_rating: 4,
      average_rating: 4,
      rating_count: 1,
      read_count: 3,
      issue_count: 10,
      progress_scope: 'thread',
    },
    routes: [{ kind: 'group', name: 'Reading Order A' }],
    overflow_routes_count: 0,
  }],
  last_read: { issue_id: 90, issue_number: '3', thread_id: 7, thread_title: 'The Good Comics', read_at: '2026-10-29T14:00:00Z' },
  snoozed_threads: [],
  snoozed_count: 0,
  skipped_thread_ids: [],
  skipped_threads: [],
  blocked_count: 0,
  blocked_threads: [],
  stale_thread_count: 0,
  stale_thread: null,
  timezone: 'America/Chicago',
}

beforeEach(() => {
  client.get.mockReset().mockResolvedValue(nativeResponse)
})

it('serves the visible Roll page from Rust v2 and adapts its issue-bearing candidates', async () => {
  const state = await rollBootstrap.get('America/Chicago')

  expect(client.get).toHaveBeenCalledExactlyOnceWith('/v2/roll/bootstrap', {
    params: { timezone: 'America/Chicago' },
  })
  expect(state).toMatchObject({
    session_id: 23,
    pending_thread_id: 7,
    last_rolled_result: 2,
    roll_pool: [{
      id: 7,
      title: 'The Good Comics',
      issue_id: 91,
      issue_number: '4',
      route_labels: ['Reading Order A'],
    }],
    last_read: { issue_id: 90 },
  })
  expect(state.roll_pool).toHaveLength(1)
})

it('uses the same native v2 projection for protected mutation recovery, without a Python v1 fallback', async () => {
  const recovered = await protectedMutations.bootstrap()

  expect(client.get).toHaveBeenCalledExactlyOnceWith(
    '/v2/roll/bootstrap',
    { skipAuthRedirect: true },
  )
  expect(recovered.roll_pool[0].issue_id).toBe(91)
  expect(recovered.pending_thread_id).toBe(7)
})

it('fails visibly instead of replacing a malformed native response with a hidden v1 request', async () => {
  client.get.mockResolvedValueOnce({ session_id: 23 })

  await expect(rollBootstrap.get()).rejects.toThrow()
  expect(client.get).toHaveBeenCalledTimes(1)
  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap')
})
