import { useMutation } from '@tanstack/react-query'
import { rollApi } from '../services/api'
import type { RollApi } from '../services/apiTypes'
import type { OverrideRollPayload } from '../types'

function getRollApi(api?: RollApi): RollApi {
  return api ?? rollApi
}

export function useRoll(api?: RollApi) {
  const rollApiInstance = getRollApi(api)
  const mutation = useMutation({
    mutationFn: () => rollApiInstance.roll(),
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}

export function useOverrideRoll(api?: RollApi) {
  const rollApiInstance = getRollApi(api)
  const mutation = useMutation({
    mutationFn: (data: OverrideRollPayload) => rollApiInstance.override(data),
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}

export function useDismissPending(api?: RollApi) {
  const rollApiInstance = getRollApi(api)
  const mutation = useMutation({
    mutationFn: () => rollApiInstance.dismissPending(),
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}

export function useSetDie(api?: RollApi) {
  const rollApiInstance = getRollApi(api)
  const mutation = useMutation({
    mutationFn: (die: number) => rollApiInstance.setDie(die),
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}

export function useClearManualDie(api?: RollApi) {
  const rollApiInstance = getRollApi(api)
  const mutation = useMutation({
    mutationFn: () => rollApiInstance.clearManualDie(),
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}

export function useReroll(api?: RollApi) {
  const rollApiInstance = getRollApi(api)
  const mutation = useMutation({
    mutationFn: () => rollApiInstance.reroll(),
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}
