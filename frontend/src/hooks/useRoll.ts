import { useMutation } from '@tanstack/react-query'
import { rollApi } from '../services/api'
import type { OverrideRollPayload } from '../types'

export function useRoll() {
  const mutation = useMutation({
    mutationFn: () => rollApi.roll(),
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}

export function useOverrideRoll() {
  const mutation = useMutation({
    mutationFn: (data: OverrideRollPayload) => rollApi.override(data),
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}

export function useDismissPending() {
  const mutation = useMutation({
    mutationFn: () => rollApi.dismissPending(),
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}

export function useSetDie() {
  const mutation = useMutation({
    mutationFn: (die: number) => rollApi.setDie(die),
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}

export function useClearManualDie() {
  const mutation = useMutation({
    mutationFn: () => rollApi.clearManualDie(),
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}

export function useReroll() {
  const mutation = useMutation({
    mutationFn: () => rollApi.reroll(),
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}
