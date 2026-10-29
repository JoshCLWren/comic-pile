import { defaultHttpClient, type HttpClient } from './httpClient'
import type { RollResponse } from '../types'

/** The legacy die label every die-mode endpoint answers with (`d6`, `d20`). */
const DIE_LABEL_PATTERN = /^d(\d+)$/

/**
 * Read the die size out of a `d<size>` response body.
 *
 * `POST /roll/clear-manual-die` documents and tests that it answers with the
 * automatic die the ladder resumes at once the manual override is gone
 * (`tests/test_roll_api.py::test_clear_manual_die_returns_correct_current_die_regression`).
 * Reading it here is what lets the Roll page apply the authoritative die
 * immediately instead of guessing or waiting for a bootstrap refetch (#4279).
 *
 * @param label - Raw response body from a die-mode endpoint.
 * @returns The die size, or null when the body is not a die label.
 */
function parseDieLabel(label: unknown): number | null {
  if (typeof label !== 'string') return null
  const match = DIE_LABEL_PATTERN.exec(label.trim())
  return match ? Number(match[1]) : null
}

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
    clearManualDie: async () =>
      parseDieLabel(await client.post<unknown>('/v1/roll/clear-manual-die')),
  }
}

export const rollApi = createRollApi(defaultHttpClient())
