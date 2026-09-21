import { type ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSessionMode } from '../hooks/useSessionMode'
import type { SessionModeUpdateRequest, SessionModeResponse } from '../types'

const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function makeSessionApi() {
  return { updateMode: vi.fn() }
}

const sessionApi = makeSessionApi()
const invalidateAfterSessionModeUpdate = vi.fn()
const cacheEffects = {
  applyRatedThreadCache: vi.fn(),
  invalidateCurrentSessionAfterSnooze: vi.fn(),
  invalidateAfterSessionModeUpdate,
}
const deps = { sessionApi, cacheEffects }

const modeResponse: SessionModeResponse = {
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

const modePatch: SessionModeUpdateRequest = {
  bandwidth: 'balanced',
  intent: 'explore',
}

function renderSessionMode() {
  return renderHook(() => useSessionMode(deps), { wrapper })
}

describe('useSessionMode', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionApi.updateMode.mockResolvedValue(modeResponse)
    invalidateAfterSessionModeUpdate.mockResolvedValue(undefined)
  })

  it('calls sessionApi.updateMode and invalidates cache on success', async () => {
    const hook = renderSessionMode()

    await act(async () => await hook.result.current.mutate(modePatch))

    expect(sessionApi.updateMode).toHaveBeenCalledWith(modePatch)
    expect(invalidateAfterSessionModeUpdate).toHaveBeenCalledWith(client)
    expect(hook.result.current.isPending).toBe(false)
    expect(hook.result.current.isError).toBe(false)
  })

  it('exposes mutate and mutateAsync', async () => {
    const hook = renderSessionMode()

    await act(async () => await hook.result.current.mutate(modePatch))

    expect(hook.result.current.mutate).toBeDefined()
    expect(hook.result.current.mutateAsync).toBeDefined()
  })

  it('sets isPending during mutation and then settles', async () => {
    let resolveRequest: () => void | undefined
    sessionApi.updateMode.mockReturnValue(new Promise((resolve) => {
      resolveRequest = () => resolve(modeResponse)
    }))

    const hook = renderSessionMode()

    const mutationPromise = act(async () => hook.result.current.mutate(modePatch))

    await waitFor(() => expect(hook.result.current.isPending).toBe(true))

    await act(async () => {
      resolveRequest?.()
      await mutationPromise
    })

    await waitFor(() => expect(hook.result.current.isPending).toBe(false))
  })
})
