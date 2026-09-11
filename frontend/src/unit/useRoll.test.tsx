import { type ReactNode } from 'react'
import { act, renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import {
  useClearManualDie,
  useDismissPending,
  useOverrideRoll,
  useReroll,
  useRoll,
  useSetDie,
} from '../hooks/useRoll'
import { rollApi } from '../services/api'
import type { OverrideRollPayload } from '../types'
import { cast } from '../utils/cast'

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

vi.mock('../services/api', () => ({
  rollApi: {
    roll: vi.fn(),
    override: vi.fn(),
    dismissPending: vi.fn(),
    setDie: vi.fn(),
    clearManualDie: vi.fn(),
    reroll: vi.fn(),
  },
}))

const mockedRollApi = vi.mocked(rollApi)

async function setupMutation<TReturn>(
  hook: () => { mutate: () => Promise<TReturn> },
): Promise<void>
async function setupMutation<TArg, TReturn>(
  hook: () => { mutate: (args: TArg) => Promise<TReturn> },
  args: TArg,
): Promise<void>
async function setupMutation<TArg, TReturn>(
  hook: () => { mutate: (args?: TArg) => Promise<TReturn> },
  args?: TArg,
): Promise<void> {
  const { result } = renderHook(() => hook(), { wrapper })

  await act(async () => {
    // SAFETY: Generic test harness forwards the typed args to the hook's mutate; cast is safe because args match the mutation contract.
    await result.current.mutate(cast<Parameters<typeof result.current.mutate>[0]>(args))
  })
}

beforeEach(() => {
  // SAFETY: Mocked roll payload is not inspected by the assertions; empty object satisfies the success path shape.
  mockedRollApi.roll.mockResolvedValue(cast<Awaited<ReturnType<typeof mockedRollApi.roll>>>({}))
  // SAFETY: Override mock uses the same empty success shape; safe because only call count is asserted.
  mockedRollApi.override.mockResolvedValue(cast<Awaited<ReturnType<typeof mockedRollApi.override>>>({}))
  // SAFETY: dismissPending resolves void; undefined is the expected value.
  mockedRollApi.dismissPending.mockResolvedValue(cast<Awaited<ReturnType<typeof mockedRollApi.dismissPending>>>(undefined))
  // SAFETY: setDie resolves void; undefined matches the mocked resolution.
  mockedRollApi.setDie.mockResolvedValue(cast<Awaited<ReturnType<typeof mockedRollApi.setDie>>>(undefined))
  // SAFETY: clearManualDie resolves void; undefined preserves the contract.
  mockedRollApi.clearManualDie.mockResolvedValue(cast<Awaited<ReturnType<typeof mockedRollApi.clearManualDie>>>(undefined))
  // SAFETY: reroll mock returns an empty roll success shape that the test does not inspect.
  mockedRollApi.reroll.mockResolvedValue(cast<Awaited<ReturnType<typeof mockedRollApi.reroll>>>({}))
})

it('calls roll mutation', async () => {
  await setupMutation(useRoll, undefined)
  expect(mockedRollApi.roll).toHaveBeenCalled()
})

it('calls override mutation', async () => {
  const payload: OverrideRollPayload = { thread_id: 9 }
  await setupMutation(useOverrideRoll, payload)
  expect(mockedRollApi.override).toHaveBeenCalledWith(payload)
})

it('calls dismiss pending mutation', async () => {
  await setupMutation(useDismissPending, undefined)
  expect(mockedRollApi.dismissPending).toHaveBeenCalled()
})

it('calls set die mutation', async () => {
  await setupMutation(useSetDie, 12)
  expect(mockedRollApi.setDie).toHaveBeenCalledWith(12)
})

it('calls clear manual die mutation', async () => {
  await setupMutation(useClearManualDie, undefined)
  expect(mockedRollApi.clearManualDie).toHaveBeenCalled()
})

it('calls reroll mutation', async () => {
  await setupMutation(useReroll, undefined)
  expect(mockedRollApi.reroll).toHaveBeenCalled()
})
