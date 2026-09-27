import { defaultHttpClient, type HttpClient } from './httpClient'
import type { RollResponse } from '../types'

/**
 * Build the roll service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every roll request.
 * @returns The roll API bound to `client`.
 */
export function createRollApi(client: HttpClient) {
  return {
    roll: () => client.post<RollResponse>('/v1/roll/'),
    override: (data: { thread_id: number }) => client.post<RollResponse, { thread_id: number }>('/v1/roll/override', data),
    dismissPending: () => client.post<void>('/v1/roll/dismiss-pending'),
    skip: () => client.post<RollResponse>('/v1/roll/skip'),
    reroll: () => client.post<RollResponse>('/v1/roll/'),
    setDie: (die: number) => client.post<void>('/v1/roll/set-die', null, { params: { die } }),
    clearManualDie: () => client.post<void>('/v1/roll/clear-manual-die'),
  }
}

export const rollApi = createRollApi(defaultHttpClient())
