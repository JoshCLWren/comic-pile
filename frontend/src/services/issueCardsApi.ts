import { defaultHttpClient, type HttpClient } from './httpClient'
import type {
  IssueCardsRequest,
  IssueCardsResponse,
  IssueReadRateRequest,
  IssueReadRateResponse as NativeIssueReadRateResponse,
} from '../generated/nativeV2Client'
import { clearPendingSelectionForIssue } from './rollPendingSelection'
import type { Tag } from './api-tags'

export type IssueCard = IssueCardsResponse['items'][number]
export type IssueReadRateResponse = NativeIssueReadRateResponse

/** Validate card tags at the generated-wire boundary before UI consumers use them. */
export function parseIssueCardTags(
  tags: IssueCard['tags'],
): Tag[] {
  if (!tags) return []
  return tags.flatMap((tag) => {
    if (tag.scope !== 'global' && tag.scope !== 'private') return []
    return [{
      id: tag.id,
      name: tag.name,
      normalized_name: tag.normalized_name,
      scope: tag.scope,
      owner_user_id: tag.owner_user_id ?? null,
      color: tag.color,
      created_at: tag.created_at,
      updated_at: tag.updated_at,
    }]
  })
}

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
  /** Alternate overall/story number (#4652). Omit to leave unchanged; null/empty to clear. */
  issueNumberAlias?: string | null
  /** True when issueNumberAlias is intentionally being set/cleared. */
  issueNumberAliasProvided?: boolean
  /** Client-generated retry key; required by the native contract. */
  idempotencyKey: string
}

/**
 * Build the issue-card service bound to an HTTP client.
 *
 * Reads are owner-scoped batched projections (`POST /v2/issues/cards`) that
 * carry issue identity, read status, stored rating, confirmed mapping state
 * and the exact provider CDN URL string — never image bytes. Writes are the
 * native direct command (`PATCH /api/v2/issues/{issue_id}`) with
 * `source: 'direct'`, so a manual read never steps the die or repositions the
 * queue.
 *
 * @param client - HTTP transport used for every issue-card request.
 * @returns The issue-card API bound to `client`.
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
        const body: IssueCardsRequest['body'] = { issue_ids: chunk }
        const response = await client.post<IssueCardsResponse, typeof body>(
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
      const body: IssueReadRateRequest['body'] & { issue_number_alias?: string | null } = {
        idempotency_key: mutation.idempotencyKey,
        source: 'direct',
      }
      if (mutation.status != null) body.status = mutation.status
      if (mutation.rating != null) body.rating = mutation.rating
      if (mutation.issueNumberAliasProvided) body.issue_number_alias = mutation.issueNumberAlias ?? null
      const response = await client.patch<IssueReadRateResponse, typeof body>(
        `/v2/issues/${encodeURIComponent(String(issueId))}`,
        body,
      )
      if (mutation.status === 'read' || mutation.rating != null) {
        clearPendingSelectionForIssue(issueId)
      }
      return response
    },
  }
}

/** The process-wide issue-card service the app and its tests bind to. */
export const issueCardsApi = createIssueCardsApi(defaultHttpClient())
