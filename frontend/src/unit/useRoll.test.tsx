import { act, renderHook } from '@testing-library/react'
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

async function setupMutation(
  hook: () => { mutate: () => Promise<unknown> },
): Promise<void>
async function setupMutation<TArg>(
  hook: () => { mutate: (args: TArg) => Promise<unknown> },
  args: TArg,
): Promise<void>
async function setupMutation<TArg>(
  hook: () => { mutate: (args?: TArg) => Promise<unknown> },
  args?: TArg,
): Promise<void> {
  const { result } = renderHook(() => hook())

  await act(async () => {
    await result.current.mutate(args as never)
  })
}

beforeEach(() => {
  mockedRollApi.roll.mockResolvedValue({} as never)
  mockedRollApi.override.mockResolvedValue({} as never)
  mockedRollApi.dismissPending.mockResolvedValue(undefined as never)
  mockedRollApi.setDie.mockResolvedValue(undefined as never)
  mockedRollApi.clearManualDie.mockResolvedValue(undefined as never)
  mockedRollApi.reroll.mockResolvedValue({} as never)
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
