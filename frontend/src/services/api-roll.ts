import { defaultHttpClient, type HttpClient } from './httpClient'
import type { RollResponse } from '../types'

type ManualDieCommand = {
  kind: 'manual_select'
  die: number
  idempotency_key: string
}

type RollOfferPayload = {
  timezone?: string
  snoozed_thread_ids: number[]
  idempotency_key: string
}

type RollOfferResponse = RollResponse & { snoozed_thread_id?: number | null }

const SNOOZE_COOKIE = 'comicpile_roll_snoozes'
const PENDING_OFFER_KEY = 'comicpile:roll:pending-offer'
const MAX_ROLL_SNOOZES = 50
const SNOOZE_COOKIE_PATTERN = /^\[\d{1,10}(,\d{1,10}){0,49}\]$/
const OFFER_KEY_PATTERN = /^roll-offer-[0-9a-f]{32}$/

function newCommandKey(): string {
  const bytes = new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  return `roll-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')}`
}

function newOfferKey(): string {
  const bytes = new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  return `roll-offer-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')}`
}

function browserTimeZone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined
  } catch {
    return undefined
  }
}

function nextMidnight(): Date {
  const midnight = new Date()
  midnight.setHours(24, 0, 0, 0)
  return midnight
}

/**
 * Temporary snoozes live only in this browser and expire at midnight.
 * The server treats them as exclusion hints, never as eligibility or auth.
 */
function readRollSnoozes(): number[] {
  try {
    const raw = globalThis.document?.cookie
      ?.split('; ')
      .find((entry) => entry.startsWith(`${SNOOZE_COOKIE}=`))
      ?.slice(SNOOZE_COOKIE.length + 1)
    if (!raw) return []
    const decoded = decodeURIComponent(raw)
    if (!SNOOZE_COOKIE_PATTERN.test(decoded)) return []
    return decoded
      .slice(1, -1)
      .split(',')
      .map((value) => Number(value))
  } catch {
    return []
  }
}

function writeRollSnoozes(ids: number[]): void {
  try {
    const bounded = Array.from(
      new Set(ids.filter((id) => Number.isSafeInteger(id) && id > 0)),
    ).slice(-MAX_ROLL_SNOOZES)
    globalThis.document.cookie = `${SNOOZE_COOKIE}=${encodeURIComponent(
      JSON.stringify(bounded),
    )}; expires=${nextMidnight().toUTCString()}; path=/; SameSite=Lax`
  } catch {
    // A blocked cookie must not disable Roll; the server still snoozes pending.
  }
}

function readPendingOfferKey(): string | null {
  try {
    const raw = globalThis.sessionStorage?.getItem(PENDING_OFFER_KEY)
    return raw && OFFER_KEY_PATTERN.test(raw) ? raw : null
  } catch {
    return null
  }
}

function writePendingOfferKey(key: string): void {
  try {
    globalThis.sessionStorage?.setItem(PENDING_OFFER_KEY, key)
  } catch {
    // In-memory retry safety remains for this page instance.
  }
}

function clearPendingOfferKey(key: string): void {
  try {
    if (readPendingOfferKey() === key) {
      globalThis.sessionStorage?.removeItem(PENDING_OFFER_KEY)
    }
  } catch {
    // The in-memory key is still cleared after a confirmed response.
  }
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
  let unresolvedOfferKey: string | null = readPendingOfferKey()

  const offer = async (): Promise<RollOfferResponse> => {
    const key = unresolvedOfferKey ?? newOfferKey()
    unresolvedOfferKey = key
    writePendingOfferKey(key)
    const response = await client.post<RollOfferResponse, RollOfferPayload>(
      '/v2/roll/offer',
      {
        timezone: browserTimeZone(),
        snoozed_thread_ids: readRollSnoozes(),
        idempotency_key: key,
      },
    )
    if (unresolvedOfferKey === key) unresolvedOfferKey = null
    clearPendingOfferKey(key)
    if (response.snoozed_thread_id) {
      writeRollSnoozes([...readRollSnoozes(), response.snoozed_thread_id])
    }
    return response
  }

  return {
    roll: offer,
    override: (data: { thread_id: number }) => client.post<RollResponse, { thread_id: number }>('/v1/roll/override', data),
    dismissPending: () => client.post<void>('/v1/roll/dismiss-pending'),
    skip: () => client.post<RollResponse>('/v1/roll/skip'),
    reroll: offer,
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
