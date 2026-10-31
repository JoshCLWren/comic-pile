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

type PendingManualDie = { die: number; key: string }
const PENDING_MANUAL_DIE_KEY = 'comicpile:roll:pending-manual-die'

// Session storage survives a refresh in this browser tab, but is not an
// authorization source. The server checks the bearer and scopes keys by user.
function readPendingManualDie(): PendingManualDie | null {
  try {
    const raw = globalThis.sessionStorage?.getItem(PENDING_MANUAL_DIE_KEY)
    // Parse the complete storage record, not individual untrusted fields.
    const match = raw?.match(/^(2|4|6|8|10|12|20):(roll-[0-9a-f]{32})$/)
    if (!match) return null
    const die = Number(match[1])
    const key = match[2]
    if (key) return { die, key }
  } catch {
    // Private browsing and storage restrictions should not disable Roll.
  }
  return null
}

function writePendingManualDie(attempt: PendingManualDie): void {
  try {
    globalThis.sessionStorage?.setItem(PENDING_MANUAL_DIE_KEY, `${attempt.die}:${attempt.key}`)
  } catch {
    // Retain in-memory retry safety when browser storage is unavailable.
  }
}

function clearPendingManualDie(key: string): void {
  try {
    if (readPendingManualDie()?.key === key) {
      globalThis.sessionStorage?.removeItem(PENDING_MANUAL_DIE_KEY)
    }
  } catch {
    // In-memory state is still cleared after a confirmed response.
  }
}

/**
 * Build the Roll API with an idempotency receipt held across ambiguous
 * network failures. A different die is a new intent; a retry of the same
 * unanswered intent reuses its original key. Successful responses clear it.
 */
export function createRollApi(client: HttpClient) {
  let unresolvedManual: PendingManualDie | null = readPendingManualDie()

  return {
    roll: () => client.post<RollResponse>('/v1/roll/'),
    override: (data: { thread_id: number }) => client.post<RollResponse, { thread_id: number }>('/v1/roll/override', data),
    dismissPending: () => client.post<void>('/v1/roll/dismiss-pending'),
    skip: () => client.post<RollResponse>('/v1/roll/skip'),
    reroll: () => client.post<RollResponse>('/v1/roll/'),
    setDie: async (die: number): Promise<void> => {
      const key = unresolvedManual?.die === die ? unresolvedManual.key : newCommandKey()
      unresolvedManual = { die, key }
      writePendingManualDie(unresolvedManual)
      await client.post<unknown, ManualDieCommand>('/v2/roll/dice-command', {
        kind: 'manual_select',
        die,
        idempotency_key: key,
      })
      if (unresolvedManual?.key === key) unresolvedManual = null
      clearPendingManualDie(key)
    },
    // Legacy auto toggle remains until the sessionless Roll UI is cut over.
    clearManualDie: () => client.post<void>('/v1/roll/clear-manual-die'),
  }
}

export const rollApi = createRollApi(defaultHttpClient())
