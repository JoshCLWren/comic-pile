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

const setupMutation = async (
  hook: () => { mutate: (args?: unknown) => Promise<unknown> },
  args?: unknown,
) => {
  const { result } = renderHook(() => hook())

  await act(async () => {
    await result.current.mutate(args)
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
  await setupMutation(useOverrideRoll, { thread_id: 9 })
  expect(mockedRollApi.override).toHaveBeenCalledWith({ thread_id: 9 })
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
