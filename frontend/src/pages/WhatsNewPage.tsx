import { useCallback, useEffect, useMemo, useState } from 'react'
import { releasesApi, type Release } from '../services/api-releases'

export const RELEASE_PAGE_SIZE = 20

type ReleaseDay = {
  key: string
  label: string
  releases: Release[]
}

type ReleaseRequest = {
  offset: number
  replace: boolean
}

function releasedAtTimestamp(release: Release) {
  const parsed = Date.parse(release.released_at)
  return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed
}

export function sortReleasesNewestFirst(releases: Release[]): Release[] {
  return [...releases].sort((left, right) => {
    const timestampDifference = releasedAtTimestamp(right) - releasedAtTimestamp(left)
    if (timestampDifference !== 0) return timestampDifference
    if (right.sort_order !== left.sort_order) return right.sort_order - left.sort_order
    return right.id - left.id
  })
}

function releaseDayKey(value: string, timeZone?: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'unknown'

  const parts = new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    timeZone,
  }).formatToParts(date)
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find(candidate => candidate.type === type)?.value ?? ''
  return `${part('year')}-${part('month')}-${part('day')}`
}

function releaseDayLabel(value: string, timeZone?: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Unknown date'
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone,
  }).format(date)
}

export function groupReleasesByDay(releases: Release[], timeZone?: string): ReleaseDay[] {
  const days: ReleaseDay[] = []
  const byKey = new Map<string, ReleaseDay>()

  for (const release of sortReleasesNewestFirst(releases)) {
    const key = releaseDayKey(release.released_at, timeZone)
    let day = byKey.get(key)
    if (!day) {
      day = {
        key,
        label: releaseDayLabel(release.released_at, timeZone),
        releases: [],
      }
      byKey.set(key, day)
      days.push(day)
    }
    day.releases.push(release)
  }

  return days
}

function ReleaseCard({ release }: { release: Release }) {
  return (
    <article className="rounded-xl border border-stone-800 bg-stone-900/50 p-4">
      <p className="text-xs font-bold uppercase tracking-[0.18em] text-amber-400">
        {release.category}
      </p>
      <h3 className="mt-1 text-lg font-bold text-stone-100">{release.title}</h3>
      <p className="mt-2 leading-7 text-stone-300">{release.summary}</p>
    </article>
  )
}

export default function WhatsNewPage() {
  const [releases, setReleases] = useState<Release[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [failedRequest, setFailedRequest] = useState<ReleaseRequest | null>(null)
  const days = useMemo(() => groupReleasesByDay(releases), [releases])
  const hasMore = releases.length < total

  const load = useCallback(async (offset: number, replace: boolean) => {
    if (replace) setLoading(true)
    else setLoadingMore(true)
    setError(null)

    try {
      const response = await releasesApi.list(RELEASE_PAGE_SIZE, offset)
      setReleases(current => replace ? response.releases : [...current, ...response.releases])
      setTotal(response.total)
      setFailedRequest(null)
    } catch (loadError) {
      setFailedRequest({ offset, replace })
      setError(
        loadError instanceof Error
          ? loadError.message
          : 'Release notes could not be loaded.',
      )
    } finally {
      if (replace) setLoading(false)
      else setLoadingMore(false)
    }
  }, [])

  useEffect(() => {
    void load(0, true)
  }, [load])

  const retry = () => {
    const request = failedRequest ?? { offset: 0, replace: true }
    void load(request.offset, request.replace)
  }

  return (
    <section aria-labelledby="whats-new-title" className="mx-auto max-w-3xl pb-8">
      <header className="mb-6 rounded-2xl border border-amber-500/20 bg-stone-950/70 p-5 shadow-lg">
        <p className="text-xs font-bold uppercase tracking-[0.22em] text-amber-400">
          ComicPile release notes
        </p>
        <h1 id="whats-new-title" className="mt-2 text-3xl font-black text-stone-100">
          What’s New
        </h1>
        <p className="mt-2 text-sm leading-6 text-stone-400">
          Recent improvements, fixes, and new ways to manage your reading pile.
        </p>
      </header>

      {loading && (
        <div role="status" className="rounded-xl border border-stone-800 bg-stone-950/60 p-6 text-stone-400">
          Loading release notes…
        </div>
      )}

      {!loading && releases.length === 0 && !error && (
        <div className="rounded-xl border border-stone-800 bg-stone-950/60 p-6 text-stone-400">
          No release notes have been published yet.
        </div>
      )}

      {error && (
        <div role="alert" className="mb-4 rounded-xl border border-red-900/60 bg-red-950/30 p-6">
          <h2 className="text-lg font-bold text-red-200">Release notes unavailable</h2>
          <p className="mt-2 text-sm text-red-100/80">{error}</p>
          <button
            type="button"
            onClick={retry}
            className="mt-4 min-h-11 rounded-lg bg-amber-400 px-4 py-2 font-bold text-stone-950"
          >
            Try again
          </button>
        </div>
      )}

      {!loading && releases.length > 0 && (
        <div className="space-y-6">
          {days.map(day => (
            <section
              key={day.key}
              aria-labelledby={`release-day-${day.key}`}
              className="rounded-2xl border border-stone-800 bg-stone-950/60 p-5"
            >
              <div className="mb-4 border-b border-stone-800 pb-3">
                <h2 id={`release-day-${day.key}`} className="text-2xl font-black text-stone-100">
                  {day.label}
                </h2>
                <p className="mt-1 text-sm text-stone-400">
                  {day.releases.length} {day.releases.length === 1 ? 'update' : 'updates'} published this day.
                </p>
              </div>
              <div className="space-y-3">
                {day.releases.map(release => (
                  <ReleaseCard key={release.id} release={release} />
                ))}
              </div>
            </section>
          ))}

          {hasMore && (
            <div className="flex justify-center">
              <button
                type="button"
                disabled={loadingMore}
                onClick={() => void load(releases.length, false)}
                className="min-h-11 rounded-lg border border-amber-500/40 bg-stone-950 px-5 py-2 font-bold text-amber-300 disabled:cursor-wait disabled:opacity-60"
              >
                {loadingMore ? 'Loading older updates…' : 'Load older updates'}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
