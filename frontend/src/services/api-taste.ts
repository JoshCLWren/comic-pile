import api from './api'

/** Explicit reader verdict for an inferred taste pattern. */
export type TasteVerdict = 'confirmed' | 'sometimes' | 'rejected'

/** One prompt-eligible inferred taste pattern. */
export interface TasteDiscovery {
  id: number
  feature_type: string
  creator_role: string | null
  label: string
  prompt: string
  evidence_count: number
  distinct_threads: number
}

/** Ranked eligible discoveries for the authenticated reader. */
export interface TasteDiscoveryListResponse {
  discoveries: TasteDiscovery[]
  generated_at: string
}

/** Canonical state of one taste signal after a response. */
export interface TasteSignalResponse {
  id: number
  feature_type: string
  creator_role: string | null
  label: string
  verdict: TasteVerdict | null
  verdict_at: string | null
  dismissed_at: string | null
  prompted_at: string | null
  prompt_count: number
}

export const tasteApi = {
  getDiscoveries: () => api.get<TasteDiscoveryListResponse>('/v1/taste/discoveries'),
  submitVerdict: (signalId: number, verdict: TasteVerdict) =>
    api.post<TasteSignalResponse>(`/v1/taste/discoveries/${signalId}/verdict`, { verdict }),
  dismiss: (signalId: number) =>
    api.post<TasteSignalResponse>(`/v1/taste/discoveries/${signalId}/dismiss`),
}
