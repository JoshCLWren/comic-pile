import { beforeEach, describe, expect, it } from 'vitest'
import { createAppQueryClient, queryClient, queryRetryPolicy } from '../query/queryClient'
import {
  getQueryRetryBudgetSnapshot,
  QUERY_OUTAGE_BUDGET,
  queryRetryDelay,
  resetQueryRetryBudget,
} from '../query/outageRetryBudget'

function responseError(status: number, detail?: string) {
  return Object.assign(new Error(`HTTP ${status}`), {
    response: {
      status,
      data: detail === undefined ? undefined : { detail },
    },
  })
}

describe('queryClient defaults', () => {
  beforeEach(() => {
    resetQueryRetryBudget()
  })

  it('configures cache and mutation behavior', () => {
    const defaults = queryClient.getDefaultOptions()

    expect(defaults.queries?.staleTime).toBe(30_000)
    expect(defaults.queries?.gcTime).toBe(5 * 60_000)
    expect(defaults.queries?.refetchOnWindowFocus).toBe(false)
    // The unit-test setup intentionally disables retries on the process-wide
    // singleton; `createAppQueryClient` below proves the production wiring.
    expect(defaults.queries?.retry).toBe(false)
    expect(defaults.queries?.retryDelay).toBe(queryRetryDelay)
    expect(defaults.mutations?.retry).toBe(false)
  })

  it('suppresses deterministic client retries and auth retries', () => {
    const retry = queryRetryPolicy
    expect(retry).toBeTypeOf('function')
    if (!(retry instanceof Function)) {
      throw new Error('Expected query retry policy to be a function')
    }

    expect(retry(0, responseError(400))).toBe(false)
    expect(retry(0, responseError(401))).toBe(false)
    expect(retry(0, responseError(403, 'Not authenticated'))).toBe(false)
    expect(retry(0, responseError(403, 'Forbidden'))).toBe(false)
    expect(retry(0, responseError(404))).toBe(false)
    expect(retry(0, responseError(409))).toBe(false)
    expect(retry(0, responseError(422))).toBe(false)
    expect(retry(0, Object.assign(new Error('canceled'), { code: 'ERR_CANCELED' }))).toBe(false)

    // Auth and deterministic failures never count toward an outage.
    expect(getQueryRetryBudgetSnapshot()).toMatchObject({
      outageActive: false,
      recentTransientFailures: 0,
    })
  })

  it('retries a single transient failure and recovers without declaring an outage', () => {
    expect(queryRetryDelay(0)).toBe(QUERY_OUTAGE_BUDGET.retryBaseDelayMs)
    expect(queryRetryPolicy(0, responseError(503))).toBe(true)
    expect(getQueryRetryBudgetSnapshot()).toMatchObject({
      outageActive: false,
      recentTransientFailures: 1,
    })
  })

  it('bounds repeated transient failures with one shared outage probe', () => {
    // First failure schedules an ordinary retry; the second recognizes the
    // shared outage and becomes the single probe; the third is suppressed.
    expect(queryRetryDelay(0)).toBe(QUERY_OUTAGE_BUDGET.retryBaseDelayMs)
    expect(queryRetryPolicy(0, responseError(503))).toBe(true)
    expect(queryRetryDelay(1)).toBe(QUERY_OUTAGE_BUDGET.probeRetryDelayMs)
    expect(queryRetryPolicy(1, responseError(503))).toBe(true)
    expect(queryRetryPolicy(2, responseError(503))).toBe(false)
    expect(getQueryRetryBudgetSnapshot()).toMatchObject({
      outageActive: true,
      probeRetriesUsed: QUERY_OUTAGE_BUDGET.maxProbeRetriesPerOutage,
    })
  })

  it('stops retrying every query while an outage is active', () => {
    expect(queryRetryPolicy(0, responseError(500))).toBe(true)
    expect(queryRetryPolicy(0, responseError(500))).toBe(true)
    // A different query failing during the outage gets no retry at all.
    expect(queryRetryPolicy(0, responseError(500))).toBe(false)
    expect(queryRetryPolicy(0, new Error('Network error. Please check your connection'))).toBe(false)
  })

  it('caps ordinary exponential retry delay deterministically', () => {
    resetQueryRetryBudget()
    expect(queryRetryDelay(0)).toBe(1_000)
    expect(queryRetryDelay(1)).toBe(2_000)
    expect(queryRetryDelay(2)).toBe(4_000)
    expect(queryRetryDelay(3)).toBe(8_000)
    expect(queryRetryDelay(8)).toBe(QUERY_OUTAGE_BUDGET.retryMaxDelayMs)
  })
})

describe('createAppQueryClient', () => {
  beforeEach(() => {
    resetQueryRetryBudget()
  })

  it('builds isolated clients with the same retry wiring', () => {
    const first = createAppQueryClient()
    const second = createAppQueryClient()

    expect(first).not.toBe(second)
    expect(first.getDefaultOptions().queries?.retry).toBe(queryRetryPolicy)
    expect(first.getDefaultOptions().queries?.retryDelay).toBe(queryRetryDelay)
  })
})
