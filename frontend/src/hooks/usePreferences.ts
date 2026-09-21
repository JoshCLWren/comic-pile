import { useQuery, useMutation } from '@tanstack/react-query'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { preferencesApi } from '../services/api'
import type { UserPreferencesResponse, UserPreferencesPatchRequest } from '../services/api'
import { applyUpdatedPreferencesCache } from '../query/cacheEffects'

export function usePreferences(enabled = true) {
  return useQuery({
    queryKey: queryKeys.preferences.detail(),
    queryFn: () => preferencesApi.get(),
    enabled,
  })
}

export function useUpdatePreferences() {
  return useMutation({
    mutationFn: (data: UserPreferencesPatchRequest) => preferencesApi.patch(data),
    onSuccess: (updatedPreferences: UserPreferencesResponse) => {
      applyUpdatedPreferencesCache(queryClient, updatedPreferences)
    },
  })
}