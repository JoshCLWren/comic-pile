import { defaultHttpClient, type HttpClient } from './httpClient'

/** Explicit reader verdict for an inferred taste pattern. */
export type TasteVerdict = 'confirmed' | 'sometimes' | 'rejected'

/** One prompt-eligible inferred taste pattern. */
export interface TasteDiscovery {
  id: number
  signal_type: string
  external_key: string
  display_name: string
  prompt: string
  evidence_count: number
  distinct_thread_count: number
}

/** Ranked eligible discoveries for the authenticated reader. */
export interface TasteDiscoveryListResponse {
  discoveries: TasteDiscovery[]
  generated_at: string
}

/** Canonical state of one taste signal after a verdict response. */
export interface TasteSignalResponse {
  user_id: number
  signal_type: string
  external_key: string
  display_name: string
  affinity_estimate: number | null
  confidence: number | null
  evidence_count: number
  distinct_thread_count: number
  user_verdict: TasteVerdict | null
  verdict_at: string | null
  first_observed_at: string | null
  last_observed_at: string | null
  last_prompted_at: string | null
}

/** AIP-134 partial update of one canonical v2 taste signal resource. */
export interface TasteSignalPatchRequest {
  user_verdict: TasteVerdict
  update_mask: ['user_verdict']
}

/**
 * Build the stable single-segment resource name for a Taste Bank signal.
 *
 * The composite `(signal_type, external_key)` identity is encoded as
 * `<signal_type>:<external_key>`; the server splits on the first colon so
 * colon-shaped external keys such as `creator:writer:dk` stay intact. Callers
 * must URL-encode the whole name before placing it in a path (#5717).
 */
export function tasteSignalName(signalType: string, externalKey: string): string {
  return `${signalType}:${externalKey}`
}

/**
 * Build the taste service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The taste service bound to `client`.
 */
export function createTasteApi(client: HttpClient) {
  return {
    getDiscoveries: () =>
      client.get<TasteDiscoveryListResponse>('/v2/users/me/tasteDiscoveries'),
    dismiss: (signalId: number) =>
      client.post<{ dismissed: boolean }>(
        `/v2/users/me/tasteDiscoveries/${signalId}:dismiss`,
      ),
    submitVerdict: (signalType: string, externalKey: string, verdict: TasteVerdict) => {
      const name = tasteSignalName(signalType, externalKey)
      const body: TasteSignalPatchRequest = {
        user_verdict: verdict,
        update_mask: ['user_verdict'],
      }
      return client.patch<TasteSignalResponse, TasteSignalPatchRequest>(
        `/v2/users/me/tasteSignals/${encodeURIComponent(name)}`,
        body,
      )
    },
  }
}

export const tasteApi = createTasteApi(defaultHttpClient())
