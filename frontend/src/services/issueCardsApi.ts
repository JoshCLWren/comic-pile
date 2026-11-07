import { defaultHttpClient, type HttpClient } from './httpClient'
import type { components } from '../generated/openapi'

export type IssueCard = components['schemas']['IssueCard']
export type IssueReadRateResponse = components['schemas']['IssueReadRateResponse']

/** Server-bound batch ceiling for one `POST /v2/issues/cards` call (#4443). */
const MAX_CARD_ISSUES = 200

/**
 * Build a client-generated idempotency key for one direct issue intent.
 * The server requires 8–128 ASCII alphanumerics plus `-`/`_`; a retry of the
 * same unanswered intent must replay the original key instead of writing twice.
 */
export function newDirectIssueKey(): string {
  const bytes = new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `direct-${hex}`
}

/** One direct read/rate write. Only the fields the shared card sends. */
export interface DirectIssueMutation {
  /** Explicit new status. Omit to leave read state unchanged. */
  status?: 'read' | 'unread' | null
  /** Effective rating in 0.5-point steps. Omit to keep the stored rating. */
  rating?: number | null
  /** Client-generated retry key; required by the native contract. */
  idempotencyKey: string
}

/**
 * Build the issue-card service bound to an HTTP client.
 *
 * Reads are owner-scoped batched projections (`POST /v2/issues/cards`) that
 * carry issue identity, read status, stored rating, confirmed mapping state
 * and the exact provider CDN URL string — never image bytes. Writes are the
 * native direct command (`PATCH /v2/issues/{issue_id}`) with `source: 'direct'`,
 * so a manual read never steps the die or repositions the queue.
 */
export function createIssueCardsApi(client: HttpClient) {
  return {
    /**
     * Fetch owner-scoped cards for a visible set of issue ids.
     * Lists longer than the server bound are split into sequential chunks so
     * a 400+ issue list issues a small bounded number of batches, never one
     * request per row.
     */
    fetchCards: async (issueIds: number[]): Promise<IssueCard[]> => {
      const unique = [...new Set(issueIds)].filter((id) => Number.isInteger(id) && id > 0)
      if (unique.length === 0) return []
      const cards: IssueCard[] = []
      for (let offset = 0; offset < unique.length; offset += MAX_CARD_ISSUES) {
        const chunk = unique.slice(offset, offset + MAX_CARD_ISSUES)
        const body: components['schemas']['IssueCardsRequest'] = { issue_ids: chunk }
        const response = await client.post<components['schemas']['IssueCardsResponse'], typeof body>(
          '/v2/issues/cards',
          body,
        )
        cards.push(...response.items)
      }
      return cards
    },

    /**
     * Apply one authenticated direct read/rate intent to an exact owned issue.
     * No Option E eligibility gate: blocked, later, excluded, inactive or
     * out-of-Roll issues remain writable by their owner.
     */
    patchIssue: async (issueId: number, mutation: DirectIssueMutation): Promise<IssueReadRateResponse> => {
      const body: components['schemas']['IssueReadRateRequest'] = {
        idempotency_key: mutation.idempotencyKey,
        source: 'direct',
      }
      if (mutation.status != null) body.status = mutation.status
      if (mutation.rating != null) body.rating = mutation.rating
      return client.patch<IssueReadRateResponse, typeof body>(
        `/v2/issues/${encodeURIComponent(String(issueId))}`,
        body,
      )
    },
  }
}

/** The process-wide issue-card service the app and its tests bind to. */
export const issueCardsApi = createIssueCardsApi(defaultHttpClient())
