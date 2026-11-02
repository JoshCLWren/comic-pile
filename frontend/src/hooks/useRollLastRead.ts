import { skipToken, useQuery } from '@tanstack/react-query'
import { queryKeys } from '../query/queryKeys'
import type { ReaderContextResponse } from '../services/api-reader-context'
import type {
  LastReadSeriesStats,
  RateResponsePayload,
  RollLastReadPayload,
} from '../types'
import { useComicVineIssueIntelligence } from './useComicVineIssueIntelligence'

/** Everything the idle last-read strip needs, resolved without a network fetch. */
export interface RollLastReadView {
  /** Identity of the session's latest rate event. */
  lastRead: RollLastReadPayload
  /** Rating saved by that event, or null when only a bootstrap record is cached. */
  rating: number | null
  /** Thread progress immediately after the rate, when the rate response is cached. */
  issuesRemaining: number | null
  totalIssues: number | null
  /** Cached provider cover art, or null when the issue has no cached cover. */
  coverUrl: string | null
  /** Canonical-series average/count, or null while identity is unresolved. */
  seriesStats: LastReadSeriesStats | null
}

function timestampFor(record: RollLastReadPayload): number {
  const parsed = Date.parse(record.read_at ?? '')
  return Number.isNaN(parsed) ? 0 : parsed
}

/**
 * Pick the newest of two last-read records without assuming which source won.
 *
 * A rate seeds the dedicated cache immediately, while a normal Roll bootstrap
 * refresh may later publish an authoritative v2 record. Comparing `read_at`
 * keeps a slower refresh from clobbering a newer rate and keeps an older cached
 * rate from masking newer committed state.
 */
function newestLastRead(
  first: RollLastReadPayload | null | undefined,
  second: RollLastReadPayload | null | undefined,
): RollLastReadPayload | null {
  if (!first) return second ?? null
  if (!second) return first
  return timestampFor(second) >= timestampFor(first) ? second : first
}

/**
 * Read the session last-read projection without issuing a request.
 *
 * The rate mutation writes the committed `RateResponse` into this cache, so the
 * strip can render the saved rating, updated series stats, and run progress
 * from data the mutation already returned (#2720). `skipToken` makes the query
 * cache-only: nothing refetches here, and there is no reader-context or
 * ComicVine fan-out just to render the strip.
 *
 * @param bootstrapLastRead - Optional last-read record from the Roll bootstrap.
 * @returns The newest available last-read view, or null when none is cached.
 */
export function useRollLastRead(
  bootstrapLastRead: RollLastReadPayload | null = null,
): RollLastReadView | null {
  const { data: cachedRate } = useQuery<RateResponsePayload | null>({
    queryKey: queryKeys.roll.lastRead(),
    queryFn: skipToken,
  })

  const rateLastRead = cachedRate?.roll_reconciliation?.last_read ?? null
  const lastRead = newestLastRead(rateLastRead, bootstrapLastRead)
  const issueId = lastRead?.issue_id ?? null

  const { metadata } = useComicVineIssueIntelligence(issueId, { enabled: false })
  const { data: readerContext } = useQuery<ReaderContextResponse | null>({
    queryKey: queryKeys.readerContext.detail(issueId ?? -1),
    queryFn: skipToken,
  })

  if (!lastRead) return null

  const fromRate = rateLastRead === lastRead ? cachedRate : null
  const series = readerContext?.series
  const identityResolved = series?.identity_source === 'comicvine'

  return {
    lastRead,
    rating: fromRate?.last_rating ?? null,
    issuesRemaining: fromRate?.issues_remaining ?? null,
    totalIssues: fromRate?.total_issues ?? null,
    coverUrl: metadata?.image_url ?? lastRead.cover_url ?? null,
    seriesStats: identityResolved
      ? {
          averageRating: series.average_rating,
          ratingCount: series.ratings_count,
          // The reader-context payload carries canonical averages but no
          // canonical run length, and an owned-issue count is not a substitute.
          readCount: null,
          issueCount: null,
          scope: 'canonical_series_run',
        }
      : null,
  }
}
