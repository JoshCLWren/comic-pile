import { type ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import { useRate } from '../hooks/useRate'
import { applyRatedThreadCache } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import { protectedRollMutationApi } from '../services/protectedRollMutationApi'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import type { RatePayload, Thread } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

// Deliberately DO NOT mock ../query/cacheEffects here: the whole point of this
// file is to exercise the real applyRatedThreadCache against a live bootstrap
// observer. The existing useRate.test.tsx mocks it and can only assert the
// option was passed, not that a second GET was actually avoided.
vi.mock('../services/protectedRollMutationApi', () => ({
  protectedRollMutationApi: { rate: vi.fn(), snooze: vi.fn(), bootstrap: vi.fn() },
}))
vi.mock('../services/rollBootstrapApi', () => ({ rollBootstrapApi: { get: vi.fn() } }))

const mockedRate = vi.mocked(protectedRollMutationApi.rate)
const mockedBootstrapGet = vi.mocked(rollBootstrapApi.get)

const thread: Thread = {
  id: 1,
  title: 'Saga',
  format: 'issue',
  issues_remaining: 3,
  total_issues: 10,
  queue_position: 2,
  status: 'active',
  is_blocked: false,
  blocking_reasons: [],
  last_activity_at: null,
  last_rating: null,
  notes: null,
  is_test: false,
  created_at: '2026-08-03T00:00:00Z',
}

const bootstrapState = (): RollBootstrapResponse => ({
  session_id: 1,
  user_id: 1,
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
})

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  })
}

/**
 * Mounts a live Roll bootstrap observer on the same client the cache effect
 * invalidates. With the default refetchType, invalidating bootstrap re-runs
 * `queryFn`, so a duplicate GET is directly observable rather than inferred.
 */
function BootstrapObserver() {
  useQuery({
    queryKey: queryKeys.roll.bootstrap(),
    queryFn: () => mockedBootstrapGet(),
    // Finite staleTime keeps the observer non-static: TanStack skips refetch
    // for queries whose observers all use a static (Infinity) staleTime.
    staleTime: 30_000,
  })
  return null
}

function Harness({ client, children }: { client: QueryClient; children: ReactNode }) {
  return (
    <QueryClientProvider client={client}>
      <BootstrapObserver />
      {children}
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedRate.mockResolvedValue(thread)
  mockedBootstrapGet.mockResolvedValue(bootstrapState())
  globalThis.document.cookie = 'comicpile_roll_snoozes=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
})

it('does not issue a second bootstrap GET when useRate owns the authoritative fetch (#5264)', async () => {
  const client = makeClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <Harness client={client}>{children}</Harness>
  )
  const { result } = renderHook(() => useRate({ queryClientInstance: client }), { wrapper })

  // Settle the observer's initial fetch, then count only the rating path.
  await waitFor(() => expect(mockedBootstrapGet).toHaveBeenCalledTimes(1))
  mockedBootstrapGet.mockClear()

  const payload: RatePayload = {
    thread_id: thread.id,
    rating: 4,
    issue_id: 1,
    source: 'roll_offer',
  }
  await act(async () => {
    await result.current.mutate(payload)
  })

  // Exactly one GET: the authoritative one owned by the rating flow. The real
  // applyRatedThreadCache ran with refetchRollBootstrap:false, so the live
  // observer above did not re-fetch. The control test below proves this
  // observer does detect a refetch when one is actually triggered.
  expect(mockedBootstrapGet).toHaveBeenCalledTimes(1)
})

it('proves the live observer detects a bootstrap refetch under the default cache effect', async () => {
  const client = makeClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <Harness client={client}>{children}</Harness>
  )
  renderHook(() => useRate({ queryClientInstance: client }), { wrapper })

  await waitFor(() => expect(mockedBootstrapGet).toHaveBeenCalledTimes(1))
  mockedBootstrapGet.mockClear()

  // Control: the default (refetching) invalidation must re-run the observer's
  // query. No code here calls the bootstrap API directly, so this single GET
  // can only have come from the live observer. That proves the observer is
  // actually watching, making the useRate test's one-GET count non-vacuous:
  // if its cache effect had refetched, that test would have seen two GETs.
  await act(async () => {
    await applyRatedThreadCache(client, thread)
  })
  await waitFor(() => expect(mockedBootstrapGet).toHaveBeenCalledTimes(1))
})
