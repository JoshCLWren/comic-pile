import { defaultHttpClient, type HttpClient } from './httpClient'
import type { RollResponse } from '../types'
import { hasProperty, isNumber, isObject, isString } from '../utils/runtimeChecks'

type ManualDieCommand = {
  kind: 'manual_select'
  die: number
  idempotency_key: string
}

type RollOfferPayload = {
  timezone?: string
  snoozed_thread_ids: number[]
  idempotency_key: string
  expected_pending_thread_id?: number
}

type RollOfferResponse = RollResponse & { snoozed_thread_id?: number | null }

type PendingOffer = { key: string; expectedPendingThreadId?: number }

const SNOOZE_COOKIE = 'comicpile_roll_snoozes'
const PENDING_OFFER_KEY = 'comicpile:roll:pending-offer'
const PENDING_RESET_KEY = 'comicpile:roll:pending-reset'
const MAX_ROLL_SNOOZES = 200
const SNOOZE_COOKIE_PATTERN = /^\[\d{1,10}(,\d{1,10}){0,199}\]$/
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

function readPendingResetKey(): string | null {
  try {
    const raw = globalThis.sessionStorage?.getItem(PENDING_RESET_KEY)
    return raw && /^roll-[0-9a-f]{32}$/.test(raw) ? raw : null
  } catch {
    return null
  }
}

function writePendingResetKey(key: string): void {
  try {
    globalThis.sessionStorage?.setItem(PENDING_RESET_KEY, key)
  } catch {
    // In-memory retry safety remains for this page instance.
  }
}

function clearPendingResetKey(key: string): void {
  try {
    if (readPendingResetKey() === key) {
      globalThis.sessionStorage?.removeItem(PENDING_RESET_KEY)
    }
  } catch {
    // The in-memory key is still cleared after a confirmed response.
  }
}

function readPendingOfferKey(): PendingOffer | null {
  try {
    const raw = globalThis.sessionStorage?.getItem(PENDING_OFFER_KEY)
    if (!raw) return null
    if (OFFER_KEY_PATTERN.test(raw)) return { key: raw }

    try {
      const parsed: unknown = JSON.parse(raw)
      if (!isObject(parsed) || !hasProperty(parsed, 'key')) return null

      const key = parsed.key
      if (!isString(key) || !OFFER_KEY_PATTERN.test(key)) return null
      if (!hasProperty(parsed, 'expectedPendingThreadId')) return { key }

      const expectedPendingThreadId = parsed.expectedPendingThreadId
      if (
        !isNumber(expectedPendingThreadId) ||
        !Number.isSafeInteger(expectedPendingThreadId) ||
        expectedPendingThreadId <= 0
      ) {
        return null
      }
      return { key, expectedPendingThreadId }
    } catch {
      // ignore parse errors
    }
    return null
  } catch {
    return null
  }
}

function writePendingOfferKey(pending: PendingOffer): void {
  try {
    globalThis.sessionStorage?.setItem(PENDING_OFFER_KEY, JSON.stringify(pending))
  } catch {
    // In-memory retry safety remains for this page instance.
  }
}

function clearPendingOfferKey(key: string): void {
  try {
    const pending = readPendingOfferKey()
    if (pending?.key === key) {
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
  let unresolvedOffer: PendingOffer | null = readPendingOfferKey()
  let unresolvedResetKey: string | null = readPendingResetKey()

  const offer = async (expectedPendingThreadId?: number): Promise<RollOfferResponse> => {
    const existing = unresolvedOffer
    let key: string
    if (existing && existing.key && existing.expectedPendingThreadId === expectedPendingThreadId) {
      key = existing.key
    } else {
      key = newOfferKey()
    }
    unresolvedOffer = { key, expectedPendingThreadId }
    writePendingOfferKey(unresolvedOffer)
    const payload: RollOfferPayload = {
      timezone: browserTimeZone(),
      snoozed_thread_ids: readRollSnoozes(),
      idempotency_key: key,
    }
    if (expectedPendingThreadId !== undefined) {
      payload.expected_pending_thread_id = expectedPendingThreadId
    }
    const response = await client.post<RollOfferResponse, RollOfferPayload>(
      '/v2/roll/offer',
      payload,
    )
    if (unresolvedOffer?.key === key) unresolvedOffer = null
    clearPendingOfferKey(key)
    if (response.snoozed_thread_id) {
      writeRollSnoozes([...readRollSnoozes(), response.snoozed_thread_id])
    }
    return response
  }

  return {
    isTemporarilySnoozed: (threadId: number): boolean =>
      readRollSnoozes().includes(threadId),
    unsnoozeTemporary: (threadId: number): void => {
      writeRollSnoozes(readRollSnoozes().filter((id) => id !== threadId))
    },
    roll: offer,
    override: (data: { thread_id: number }) => client.post<RollResponse, { thread_id: number }>('/v1/roll/override', data),
    dismissPending: () => client.post<void>('/v1/roll/dismiss-pending'),
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
    reset: async () => {
      const key = unresolvedResetKey ?? newCommandKey()
      unresolvedResetKey = key
      writePendingResetKey(key)
      const response = await client.post<
        { die: number; replayed: boolean },
        { idempotency_key: string }
      >('/v2/roll/reset', { idempotency_key: key })
      if (unresolvedResetKey === key) unresolvedResetKey = null
      clearPendingResetKey(key)
      // Reset Dice clears this browser's temporary snoozes by definition.
      writeRollSnoozes([])
      // A reset discards the pre-reset intent: never replay an unanswered
      // offer or manual-die key against the fresh state.
      unresolvedOffer = null
      unresolvedManual = null
      try {
        globalThis.sessionStorage?.removeItem(PENDING_OFFER_KEY)
        globalThis.sessionStorage?.removeItem(PENDING_MANUAL_DIE_KEY)
      } catch {
        // The in-memory keys above are still cleared.
      }
      return response
    },
  }
}

export const rollApi = createRollApi(defaultHttpClient())

/**
 * Read the current browser snooze cookie.
 */
export function readRollSnoozes(): number[] {
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

/**
 * Write the browser snooze cookie.
 */
export function writeRollSnoozes(ids: number[]): void {
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

/**
 * Remove a thread ID from the browser snooze cookie.
 */
export function removeRollSnooze(threadId: number): void {
  const current = readRollSnoozes()
  const filtered = current.filter((id) => id !== threadId)
  writeRollSnoozes(filtered)
}
