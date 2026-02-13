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

const setupMutation = async (hook, args) => {
  const { result } = renderHook(() => hook())

  await act(async () => {
    await result.current.mutate(args)
  })
}

beforeEach(() => {
  rollApi.roll.mockResolvedValue({})
  rollApi.override.mockResolvedValue({})
  rollApi.dismissPending.mockResolvedValue({})
  rollApi.setDie.mockResolvedValue({})
  rollApi.clearManualDie.mockResolvedValue({})
  rollApi.reroll.mockResolvedValue({})
})

it('calls roll mutation', async () => {
  await setupMutation(useRoll, undefined)
  expect(rollApi.roll).toHaveBeenCalled()
})

it('calls override mutation', async () => {
  await setupMutation(useOverrideRoll, { thread_id: 9 })
  expect(rollApi.override).toHaveBeenCalledWith({ thread_id: 9 })
})

it('calls dismiss pending mutation', async () => {
  await setupMutation(useDismissPending, undefined)
  expect(rollApi.dismissPending).toHaveBeenCalled()
})

it('calls set die mutation', async () => {
  await setupMutation(useSetDie, 12)
  expect(rollApi.setDie).toHaveBeenCalledWith(12)
})

it('calls clear manual die mutation', async () => {
  await setupMutation(useClearManualDie, undefined)
  expect(rollApi.clearManualDie).toHaveBeenCalled()
})

it('calls reroll mutation', async () => {
  await setupMutation(useReroll, undefined)
  expect(rollApi.reroll).toHaveBeenCalled()
})
