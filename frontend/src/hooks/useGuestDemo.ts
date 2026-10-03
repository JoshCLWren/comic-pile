import { useMutation, useQuery } from '@tanstack/react-query'
import { guestDemoApi } from '../services/api-guest-demo'
import type { RollResponse, RollBootstrapResponse } from '../types'

export function useGuestDemoRoll() {
  return useMutation({
    mutationFn: () => guestDemoApi.roll(),
    mutationKey: ['guest-demo', 'roll'],
  })
}

export function useGuestDemoBootstrap() {
  return useQuery({
    queryFn: () => guestDemoApi.bootstrap(),
    queryKey: ['guest-demo', 'bootstrap'],
    staleTime: 30 * 1000, // 30 seconds
    gcTime: 5 * 60 * 1000, // 5 minutes
  })
}