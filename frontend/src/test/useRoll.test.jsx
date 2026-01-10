import { act, renderHook, waitFor } from '@testing-library/react'
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
import { createQueryWrapper, createTestQueryClient } from './testUtils'

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

const setupMutation = async (hook, args, expectedInvalidations) => {
  const queryClient = createTestQueryClient()
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
  const wrapper = createQueryWrapper(queryClient)
  const { result } = renderHook(() => hook(), { wrapper })

  await act(async () => {
    await result.current.mutateAsync(args)
  })

  for (const invalidation of expectedInvalidations) {
    await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: invalidation }))
  }
}

beforeEach(() => {
  rollApi.roll.mockResolvedValue({})
  rollApi.override.mockResolvedValue({})
  rollApi.dismissPending.mockResolvedValue({})
  rollApi.setDie.mockResolvedValue({})
  rollApi.clearManualDie.mockResolvedValue({})
  rollApi.reroll.mockResolvedValue({})
})

it('calls roll mutation and invalidates queries', async () => {
  await setupMutation(useRoll, undefined, [['session'], ['session', 'current'], ['threads']])
  expect(rollApi.roll).toHaveBeenCalled()
})

it('calls override mutation and invalidates queries', async () => {
  await setupMutation(useOverrideRoll, { thread_id: 9 }, [['session'], ['session', 'current'], ['threads']])
  expect(rollApi.override).toHaveBeenCalledWith({ thread_id: 9 })
})

it('calls dismiss pending mutation and invalidates session', async () => {
  await setupMutation(useDismissPending, undefined, [['session']])
  expect(rollApi.dismissPending).toHaveBeenCalled()
})

it('calls set die mutation and invalidates session', async () => {
  await setupMutation(useSetDie, 12, [['session']])
  expect(rollApi.setDie).toHaveBeenCalledWith(12)
})

it('calls clear manual die mutation and invalidates session', async () => {
  await setupMutation(useClearManualDie, undefined, [['session']])
  expect(rollApi.clearManualDie).toHaveBeenCalled()
})

it('calls reroll mutation and invalidates queries', async () => {
  await setupMutation(useReroll, undefined, [['session'], ['session', 'current'], ['threads']])
  expect(rollApi.reroll).toHaveBeenCalled()
})
