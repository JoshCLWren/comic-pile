import { defaultHttpClient, type HttpClient } from './httpClient'
import type { RollResponse } from '../types'

type ManualDieCommand = {
  kind: 'manual_select'
  die: number
  idempotency_key: string
}

function newCommandKey(): string {
  const bytes = new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  return `roll-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')}`
}

/**
 * Build the Roll API with an idempotency receipt held across ambiguous
 * network failures. A different die is a new intent; a retry of the same
 * unanswered intent reuses its original key. Successful responses clear it.
 */
export function createRollApi(client: HttpClient) {
  let unresolvedManual: { die: number; key: string } | null = null

  return {
    roll: () => client.post<RollResponse>('/v1/roll/'),
    override: (data: { thread_id: number }) => client.post<RollResponse, { thread_id: number }>('/v1/roll/override', data),
    dismissPending: () => client.post<void>('/v1/roll/dismiss-pending'),
    skip: () => client.post<RollResponse>('/v1/roll/skip'),
    reroll: () => client.post<RollResponse>('/v1/roll/'),
    setDie: async (die: number): Promise<void> => {
      const key = unresolvedManual?.die === die ? unresolvedManual.key : newCommandKey()
      unresolvedManual = { die, key }
      await client.post<unknown, ManualDieCommand>('/v2/roll/dice-command', {
        kind: 'manual_select',
        die,
        idempotency_key: key,
      })
      if (unresolvedManual?.key === key) unresolvedManual = null
    },
    // Legacy auto toggle remains until the sessionless Roll UI is cut over.
    clearManualDie: () => client.post<void>('/v1/roll/clear-manual-die'),
  }
}

export const rollApi = createRollApi(defaultHttpClient())
