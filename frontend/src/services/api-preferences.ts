import { defaultHttpClient, type HttpClient } from './httpClient'

export interface UserPreferencesResponse {
  user_id: number
  /** Legacy server field. Night Shift is the only identity; clients ignore it (#5980). */
  theme?: string
}

/**
 * No appearance field is writable: Night Shift is fixed and there is no theme
 * preference to persist. The endpoint remains part of the API surface for any
 * future unrelated preference fields.
 */
export type UserPreferencesPatchRequest = Record<string, never>

/**
 * Build the user preferences service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every preferences request.
 * @returns The preferences API bound to `client`.
 */
export function createPreferencesApi(client: HttpClient) {
  return {
    get: (options?: { timeout?: number; skipAuthRedirect?: boolean }) =>
      client.get<UserPreferencesResponse>('/v2/users/me/preferences', options),
    patch: (data: UserPreferencesPatchRequest) =>
      client.patch<UserPreferencesResponse, UserPreferencesPatchRequest>('/v2/users/me/preferences', data),
  }
}

export const preferencesApi = createPreferencesApi(defaultHttpClient())
