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

/**
 * Build the taste service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The taste service bound to `client`.
 */
export function createTasteApi(client: HttpClient) {
  return {
    getDiscoveries: () => client.get<TasteDiscoveryListResponse>('/v1/taste/discoveries'),
    dismiss: (signalId: number) =>
      client.post<{ dismissed: boolean }>(`/v1/taste/discoveries/${signalId}/dismiss`),
    submitVerdict: (signalType: string, externalKey: string, verdict: TasteVerdict) =>
      client.put<TasteSignalResponse>(
        `/v1/users/me/taste-signals/${encodeURIComponent(signalType)}/${encodeURIComponent(externalKey)}/verdict`,
        { verdict },
      ),
  }
}

export const tasteApi = createTasteApi(defaultHttpClient())
