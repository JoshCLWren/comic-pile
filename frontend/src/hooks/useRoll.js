import { useMutation, useQueryClient } from '@tanstack/react-query'
import { rollApi } from '../services/api'

export function useRoll() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => rollApi.roll(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session'] })
      queryClient.invalidateQueries({ queryKey: ['threads'] })
    },
  })
}

export function useOverrideRoll() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data) => rollApi.override(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session'] })
      queryClient.invalidateQueries({ queryKey: ['threads'] })
    },
  })
}

export function useDismissPending() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => rollApi.dismissPending(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session'] })
    },
  })
}

export function useSetDie() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (die) => rollApi.setDie(die),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session'] })
    },
  })
}

export function useClearManualDie() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => rollApi.clearManualDie(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session'] })
    },
  })
}

export function useReroll() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => rollApi.reroll(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session'] })
      queryClient.invalidateQueries({ queryKey: ['threads'] })
    },
  })
}
