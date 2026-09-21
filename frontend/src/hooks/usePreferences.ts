import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  applyTheme,
  ensureThemeApplied,
  getThemeSelectionToken,
  isSupportedTheme,
  readStoredThemePreference,
} from '../services/theme'
import { queryKeys } from '../query/queryKeys'
import { preferencesApi } from '../services/api'
import type { UserPreferencesResponse, UserPreferencesPatchRequest } from '../services/api'
import { applyUpdatedPreferencesCache } from '../query/cacheEffects'
import { getThemePreferenceRetryDelays } from '../services/themePreferenceSync'

const PREFERENCES_TIMEOUT_MS = 15_000

export function usePreferences(enabled = true) {
  return useQuery({
    queryKey: queryKeys.preferences.detail(),
    queryFn: () =>
      preferencesApi.get({
        timeout: PREFERENCES_TIMEOUT_MS,
        skipAuthRedirect: true,
      }),
    enabled,
  })
}

export function useUpdatePreferences(onFailure?: () => void) {
  const client = useQueryClient()
  const latestMutation = useRef(0)

  return useMutation({
    mutationFn: (data: UserPreferencesPatchRequest) => preferencesApi.patch(data),
    retry: (failureCount) => failureCount < 3,
    retryDelay: (attemptIndex) => getThemePreferenceRetryDelays()[attemptIndex] ?? 0,
    onMutate: () => {
      latestMutation.current += 1
      return { generation: latestMutation.current }
    },
    onSuccess: (updatedPreferences, _variables, context) => {
      if (context?.generation !== latestMutation.current) return
      applyUpdatedPreferencesCache(client, updatedPreferences)
    },
    onError: (_error, _variables, context) => {
      if (context?.generation === latestMutation.current) {
        onFailure?.()
      }
    },
  })
}

export function PreferencesSync({ isAuthenticated }: { isAuthenticated: boolean }) {
  const { data, isError } = usePreferences(isAuthenticated)
  const { mutate: updatePreferences } = useUpdatePreferences()
  const selectionTokenAtStart = getThemeSelectionToken()

  useEffect(() => {
    if (isError) {
      ensureThemeApplied()
      return
    }
    if (!data || getThemeSelectionToken() !== selectionTokenAtStart) {
      return
    }

    const theme = data.theme
    if (isSupportedTheme(theme)) {
      const storedTheme = readStoredThemePreference()
      if (storedTheme === null || theme === storedTheme) {
        applyTheme(theme)
      } else {
        ensureThemeApplied()
        updatePreferences({ theme: storedTheme })
      }
    } else {
      ensureThemeApplied()
    }
  }, [data, isError, selectionTokenAtStart, updatePreferences])

  return null
}
