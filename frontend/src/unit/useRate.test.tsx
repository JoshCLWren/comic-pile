import { type ReactNode } from 'react'
import { act, renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import { useRate } from '../hooks/useRate'
import { ROLL_BOOTSTRAP_RECONCILED_EVENT } from '../hooks/rollMutationReconciliation'
import { applyRatedThreadCache } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { protectedRollMutationApi } from '../services/protectedRollMutationApi'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import type { RatePayload, Thread } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import { cast } from '../utils/cast'

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

vi.mock('../services/protectedRollMutationApi', () => ({ protectedRollMutationApi: { rate: vi.fn(), snooze: vi.fn(), bootstrap: vi.fn() } }))
vi.mock('../services/rollBootstrapApi', () => ({ rollBootstrapApi: { get: vi.fn() } }))
vi.mock('../query/cacheEffects', () => ({ applyRatedThreadCache: vi.fn() }))

const mockedProtectedApi = vi.mocked(protectedRollMutationApi)
const mockedRollBootstrapApi = vi.mocked(rollBootstrapApi)
const mockedApplyRatedThreadCache = vi.mocked(applyRatedThreadCache)
const thread: Thread = { id: 1, title: 'Saga', format: 'issue', issues_remaining: 3, total_issues: 10, queue_position: 2, status: 'active', is_blocked: false, blocking_reasons: [], last_activity_at: null, last_rating: null, notes: null, is_test: false, created_at: '2026-08-03T00:00:00Z' }
const bootstrapState = (pendingThreadId: number | null, sessionId = 1): RollBootstrapResponse => ({ session_id: sessionId, user_id: 1, pending_thread_id: pendingThreadId, last_rolled_result: pendingThreadId === null ? null : 1, session_mode: { active_bandwidth: null, predicted_bandwidth: null, bandwidth_confidence: null, bandwidth_source: null, bandwidth_version: null, active_intent: null, predicted_intent: null, intent_confidence: null, intent_source: null, intent_version: null, session_mode_correction_guidance: null }, active_thread: null, roll_pool: [], snoozed_threads: [], snoozed_count: 0, skipped_thread_ids: [], skipped_threads: [] })

beforeEach(() => { vi.clearAllMocks(); mockedProtectedApi.rate.mockResolvedValue(thread); mockedRollBootstrapApi.get.mockResolvedValue(bootstrapState(null)); mockedApplyRatedThreadCache.mockResolvedValue(); globalThis.document.cookie = 'comicpile_roll_snoozes=; expires=Thu, 01 Jan 1970 00:00:00 GMT' })

it('submits ratings, applies the authoritative thread cache, and publishes Roll state', async () => {
  const reconciled = vi.fn(); window.addEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, reconciled)
  try { const { result } = renderHook(() => useRate(), { wrapper }); const payload: RatePayload = { thread_id: 1, rating: 4, issue_id: 1, source: 'roll_offer' }; let response: Awaited<ReturnType<typeof result.current.mutate>> | undefined; await act(async () => { response = await result.current.mutate(payload) }); expect(mockedProtectedApi.rate).toHaveBeenCalledWith(payload); expect(mockedApplyRatedThreadCache).toHaveBeenCalledWith(queryClient, thread); expect(response?.rate).toBe(thread); expect(response?.bootstrap).toEqual(bootstrapState(null)); expect(mockedRollBootstrapApi.get).toHaveBeenCalledTimes(1); expect(reconciled).toHaveBeenCalledTimes(1); expect(result.current.isError).toBe(false) } finally { window.removeEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, reconciled) }
})

it('shares one in-flight request across repeated submissions', async () => {
  let resolveRequest: (() => void) | undefined
  // SAFETY: Test controls promise resolution; resolving with undefined satisfies the mocked rate promise that the hook awaits.
  mockedProtectedApi.rate.mockReturnValue(
    new Promise((resolve) => {
      resolveRequest = () => resolve(cast<Thread>(undefined))
    }),
  )
  const { result } = renderHook(() => useRate(), { wrapper })
  const payload: RatePayload = { thread_id: 1, rating: 4, issue_id: 1, source: 'roll_offer' }
  let firstRequest: Promise<unknown> | undefined
  let secondRequest: Promise<unknown> | undefined
  act(() => {
    firstRequest = result.current.mutate(payload)
    secondRequest = result.current.mutate(payload)
  })
  expect(mockedProtectedApi.rate).toHaveBeenCalledTimes(1)
  expect(result.current.isPending).toBe(true)
  await act(async () => {
    resolveRequest?.()
    await Promise.all([firstRequest, secondRequest])
  })
  expect(mockedApplyRatedThreadCache).toHaveBeenCalledTimes(1)
  expect(mockedRollBootstrapApi.get).toHaveBeenCalledTimes(1)
  expect(result.current.isPending).toBe(false)
  expect(result.current.isError).toBe(false)
})

it('reconciles a committed rating after the delayed response crosses the client timeout', async () => {
  vi.useFakeTimers(); const timeout = Object.assign(new Error('timeout of 10000ms exceeded'), { code: 'ECONNABORTED' }); mockedProtectedApi.rate.mockImplementation(() => new Promise((_, reject) => { setTimeout(() => reject(timeout), 10_000) })); mockedRollBootstrapApi.get.mockResolvedValue(bootstrapState(null, 10));
  // SAFETY: fake timers only; the hook's delayed reconciliation is awaited below.
  try { const { result } = renderHook(() => useRate(), { wrapper }); const payload: RatePayload = { thread_id: 1, rating: 3, issue_id: 1, source: 'roll_offer' }; let firstRequest: Promise<unknown> | undefined; let secondRequest: Promise<unknown> | undefined; act(() => { firstRequest = result.current.mutate(payload); secondRequest = result.current.mutate(payload) }); expect(mockedProtectedApi.rate).toHaveBeenCalledTimes(1); expect(result.current.isPending).toBe(true); await act(async () => { await vi.advanceTimersByTimeAsync(10_000); await Promise.all([firstRequest, secondRequest]) }); expect(mockedApplyRatedThreadCache).not.toHaveBeenCalled(); expect(mockedRollBootstrapApi.get).toHaveBeenCalledTimes(2); expect(globalThis.document.cookie).toContain('%5B1%5D'); expect(result.current.isError).toBe(false); expect(result.current.isPending).toBe(false) } finally { vi.useRealTimers() }
})

it('surfaces a delayed timeout when authoritative state still has the same pending thread', async () => {
  vi.useFakeTimers(); const timeout = Object.assign(new Error('timeout of 10000ms exceeded'), { code: 'ECONNABORTED' }); mockedProtectedApi.rate.mockImplementation(() => new Promise((_, reject) => { setTimeout(() => reject(timeout), 10_000) })); mockedRollBootstrapApi.get.mockResolvedValue(bootstrapState(1));
  try { const { result } = renderHook(() => useRate(), { wrapper }); const payload: RatePayload = { thread_id: 1, rating: 3, issue_id: 1, source: 'roll_offer' }; let request!: Promise<unknown>; act(() => { request = result.current.mutate(payload) }); const rejection = expect(request).rejects.toBe(timeout); await act(async () => { await vi.advanceTimersByTimeAsync(10_000); await rejection }); expect(mockedApplyRatedThreadCache).not.toHaveBeenCalled(); expect(mockedRollBootstrapApi.get).toHaveBeenCalledTimes(1); expect(result.current.isError).toBe(true); expect(result.current.isPending).toBe(false) } finally { vi.useRealTimers() }
})

it('keeps a successful rating successful when the follow-up bootstrap refresh fails', async () => {
  mockedRollBootstrapApi.get.mockRejectedValue(new Error('refresh unavailable'))
  const { result } = renderHook(() => useRate(), { wrapper })
  await act(async () => { await expect(result.current.mutate({ thread_id: 1, rating: 4, issue_id: 1, source: 'roll_offer' })).resolves.toEqual({ rate: thread, bootstrap: null }) })
  expect(result.current.isError).toBe(false)
})

it('marks ordinary rating failures as errors and rethrows them', async () => {
  const failure = new Error('rating unavailable'); mockedProtectedApi.rate.mockRejectedValue(failure)
  const { result } = renderHook(() => useRate(), { wrapper }); let request!: Promise<unknown>
  act(() => { request = result.current.mutate({ thread_id: 1, rating: 2, issue_id: 1, source: 'roll_offer' }) })
  await act(async () => { await expect(request).rejects.toBe(failure) })
  expect(result.current.isError).toBe(true); expect(result.current.isPending).toBe(false)
})

it('temporarily snoozes a below-threshold Roll rating so it leaves the next pool (#4699)', async () => {
  const { result } = renderHook(() => useRate(), { wrapper })
  await act(async () => { await result.current.mutate({ thread_id: 1, rating: 0.5, issue_id: 1, source: 'roll_offer' }) })
  expect(globalThis.document.cookie).toContain('%5B1%5D')
  expect(mockedRollBootstrapApi.get).toHaveBeenCalledTimes(1)
})

it('does not snooze at or above the rating threshold', async () => {
  const { result } = renderHook(() => useRate(), { wrapper })
  await act(async () => { await result.current.mutate({ thread_id: 1, rating: 4, issue_id: 1, source: 'roll_offer' }) })
  expect(globalThis.document.cookie).not.toContain('comicpile_roll_snoozes=%5B')
})

it('does not snooze a manual direct rating even when below threshold', async () => {
  const { result } = renderHook(() => useRate(), { wrapper })
  await act(async () => { await result.current.mutate({ thread_id: 1, rating: 0.5, issue_id: 1, source: 'direct' }) })
  expect(globalThis.document.cookie).not.toContain('comicpile_roll_snoozes=%5B')
})

it('does not snooze a finished series, which already leaves the pool', async () => {
  mockedProtectedApi.rate.mockResolvedValue({ ...thread, issues_remaining: 0, status: 'completed' })
  const { result } = renderHook(() => useRate(), { wrapper })
  await act(async () => { await result.current.mutate({ thread_id: 1, rating: 0.5, issue_id: 1, source: 'roll_offer' }) })
  expect(globalThis.document.cookie).not.toContain('comicpile_roll_snoozes=%5B')
})
