import { defaultHttpClient, type HttpClient } from './httpClient'

export interface UserPreferencesResponse {
  theme: 'classic' | 'ink-gold' | 'command-center'
  user_id: number
}

export interface UserPreferencesPatchRequest {
  theme?: 'classic' | 'ink-gold' | 'command-center' | null
}

/**
 * Build the user preferences service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every preferences request.
 * @returns The preferences API bound to `client`.
 */
export function createPreferencesApi(client: HttpClient) {
  return {
    get: (options?: { timeout?: number; skipAuthRedirect?: boolean }) =>
      client.get<UserPreferencesResponse>('/v1/users/me/preferences', options),
    patch: (data: UserPreferencesPatchRequest) =>
      client.patch<UserPreferencesResponse, UserPreferencesPatchRequest>('/v1/users/me/preferences', data),
  }
}

export const preferencesApi = createPreferencesApi(defaultHttpClient())
