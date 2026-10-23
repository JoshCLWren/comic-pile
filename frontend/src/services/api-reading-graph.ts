/**
 * Read-only prospective reading graph used while adopting a CBL source (#4020).
 *
 * The graph is computed by the server from the same Option E evaluator and cycle
 * validator that execute the reading list (#1615, #4016, #4017, #4019). This
 * module never re-derives eligibility: it only transports the server's series
 * nodes, conflict questions, and the prospective effects of each choice. The
 * browser must never invent a second interpretation of the overlap rule.
 *
 * The endpoint contract belongs to #4019 (`Reading graph preview API`). Until it
 * ships, a missing preview endpoint is a soft failure in the adoption flow: the
 * page keeps the existing one-decision commit path and warns that overlap
 * guidance is unavailable.
 */

import { defaultHttpClient, type HttpClient } from './httpClient'

/** Exact Comic Vine series/volume identity plus its reader-facing label parts. */
export interface ReadingGraphSeriesReference {
  /** Comic Vine volume identity. Same-titled runs never share this value. */
  comicvine_volume_id: string
  series_name: string
  /** Volume/publication year, when the source declares one. */
  year: number | null
}

/** One concrete comic the graph may name as waiting or rollable. */
export interface ReadingGraphIssueReference {
  issue_id: number
  series_name: string
  issue_number: string
  comicvine_volume_id: string | null
}

/** Whether a series can keep rolling, is held, or is partly held. */
export type ReadingGraphSeriesState = 'continues' | 'waits' | 'mixed'

/** One series node of the prospective graph. */
export interface ReadingGraphSeriesNode extends ReadingGraphSeriesReference {
  state: ReadingGraphSeriesState
  unread_count: number
  rollable_count: number
  waiting_count: number
  /** Comics in this series that currently wait on another series. */
  waits_for_issue_ids: number[]
}

/** The reader's answer to one genuine series conflict. */
export type ReadingGraphOverlapChoiceId = 'protect_order' | 'continue_series'

/** Server-provided prospective effect of one answer, before it is saved. */
export interface ReadingGraphChoiceEffect {
  choice: ReadingGraphOverlapChoiceId
  /** Short reader-facing answer, e.g. "Mister Miracle waits; JLI continues". */
  label: string
  /** One sentence explaining what the answer protects. */
  detail: string
  /** Comics that can still be rolled after this answer. */
  rollable_issue_ids: number[]
  /** Comics that still wait after this answer. */
  waiting_issue_ids: number[]
  /** Complete graph state after this answer. */
  series: ReadingGraphSeriesNode[]
}

/** One genuine conflict between two exact volumes in the prospective list. */
export interface ReadingGraphOverlap {
  /**
   * Stable identity of the conflict pair. The server owns it so a restored
   * decision can be matched without re-deriving the pair in the browser.
   */
  overlap_id: string
  /** The series that would keep rolling when the reader approves continuing. */
  continuing_series: ReadingGraphSeriesReference
  /** The series whose earlier unread comics would stop holding the other one. */
  waiting_series: ReadingGraphSeriesReference
  /** Reader-facing question naming both volumes. */
  question: string
  /** Comics of the continuing series that wait only because of this conflict. */
  blocked_issue_ids: number[]
  choices: ReadingGraphChoiceEffect[]
  /** Decision already saved for this reader and list, if any. */
  selected_choice: ReadingGraphOverlapChoiceId | null
}

/** A cycle or invalid relationship the server rejected before any write. */
export interface ReadingGraphCycleError {
  code: string
  /** Reader-facing explanation naming the series/comics involved. */
  message: string
}

/** Complete read-only graph preview for one source selection. */
export interface ReadingGraphPreview {
  source_list_id: number
  content_hash: string
  revision_sha: string
  series: ReadingGraphSeriesNode[]
  overlaps: ReadingGraphOverlap[]
  issues: ReadingGraphIssueReference[]
  rollable_issue_ids: number[]
  waiting_issue_ids: number[]
  cycle_errors: ReadingGraphCycleError[]
}

/** One answer the reader has already made in this preview session. */
export interface ReadingGraphOverlapChoice {
  overlap_id: string
  choice: ReadingGraphOverlapChoiceId
}

/** Read-only request for a prospective graph: selected positions plus answers. */
export interface ReadingGraphPreviewRequest {
  /** Included CBL source positions, so the preview matches the checklist. */
  included_positions: number[]
  /** Answers already given, so each preview reflects them immediately. */
  overlap_choices: ReadingGraphOverlapChoice[]
}

/**
 * Build the reading-graph service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The reading-graph service bound to `client`.
 */
export function createReadingGraphApi(client: HttpClient) {
  return {
    /**
     * Preview the prospective graph for the current CBL selection.
     *
     * The call is read-only: it never writes owned state, list membership, or
     * overlap decisions. Answers are echoed back so the server can explain
     * their effects before the reader commits.
     */
    preview: (sourceListId: number, request: ReadingGraphPreviewRequest) =>
      client.post<ReadingGraphPreview>(
        `/v1/issue-identity/cbl/${sourceListId}/reading-graph-preview`,
        request,
      ),
  }
}

export const readingGraphApi = createReadingGraphApi(defaultHttpClient())
