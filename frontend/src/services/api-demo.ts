import { defaultHttpClient, type HttpClient } from './httpClient'
import type { RollResponse } from '../types'

/**
 * Build the guest demo service bound to an HTTP client.
 *
 * The demo surface is read-only by contract: the guest performs exactly one
 * seeded sample roll and no write endpoint exists, so this client intentionally
 * exposes no mutation method.
 *
 * @param client - HTTP transport used for every demo request.
 * @returns The demo API bound to `client`.
 */
export function createDemoApi(client: HttpClient) {
  return {
    roll: () => client.get<RollResponse>('/v1/demo/roll'),
  }
}

/** Demo service surface the guest demo page depends on. */
export type DemoApi = ReturnType<typeof createDemoApi>

export const demoApi = createDemoApi(defaultHttpClient())
