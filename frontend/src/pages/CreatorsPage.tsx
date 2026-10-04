import { Link, useSearchParams } from 'react-router-dom'
import { useCreatorsList } from '../hooks/useCreatorsList'
import type { CreatorListSort } from '../hooks/useCreatorsList'
import { useDebounce } from '../hooks/useDebounce'
import { creatorRoutePath, parseCreatorKey } from '../utils/creatorKey'
import type { CreatorListItem } from '../services/api-creators'

/** Quiet period before a typed name search becomes a new bounded query. */
const SEARCH_DEBOUNCE_MS = 300

/**
 * Server-side browse orderings exposed by `GET /api/v1/creators`. Labels stay
 * human-readable; the option value is the wire contract from #2775.
 */
const SORT_OPTIONS: ReadonlyArray<{ value: CreatorListSort; label: string }> = [
  { value: 'name', label: 'Name (A to Z)' },
  { value: 'ratings_count', label: 'Most rated' },
  { value: 'average_rating', label: 'Highest average' },
]

function isCreatorListSort(value: string): value is CreatorListSort {
  return SORT_OPTIONS.some((option) => option.value === value)
}

function CreatorRow({ item }: { item: CreatorListItem }) {
  const key = item.canonical_creator_key
  // A creator without a stable provider identity has no detail route; it must
  // stay plain text rather than link to a guessed identity.
  const detailPath = parseCreatorKey(key) != null ? creatorRoutePath(key) : null
  const roles = item.normalized_roles.join(', ')
  const ratingsCount = item.ratings_count
  const average = item.average_rating

  const body = (
    <>
      <span className="block min-w-0 break-words text-sm font-semibold" style={{ color: 'var(--theme-text-primary)' }}>
        {item.display_name}
      </span>
      <span className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
        {roles.length > 0 && <span className="break-words">{roles}</span>}
        <span>
          {ratingsCount} rated issue{ratingsCount === 1 ? '' : 's'}
        </span>
        {average != null ? (
          <span className="font-bold" style={{ color: 'var(--theme-personal-accent)' }} aria-label={`Your average rating ${average} out of 5 from ${ratingsCount} rated issues`}>
            {average.toFixed(1)}★
          </span>
        ) : (
          <span>unrated</span>
        )}
      </span>
    </>
  )

  return (
    <li className="min-w-0 rounded-xl border px-3 py-2" style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
      {detailPath ? (
        <Link
          to={detailPath}
          className="block min-w-0 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
        >
          {body}
        </Link>
      ) : (
        <div className="min-w-0">{body}</div>
      )}
    </li>
  )
}

export default function CreatorsPage() {
  const [searchParams, setSearchParams] = useSearchParams()

  const search = searchParams.get('search') || ''
  const sort = isCreatorListSort(searchParams.get('sort') || '') ? (searchParams.get('sort') as CreatorListSort) : 'name'
  const role = searchParams.get('role') || ''
  const minSampleRaw = searchParams.get('min_sample')
  const minAverageRaw = searchParams.get('min_average')
  const unread = searchParams.get('unread') === 'true'

  const minSample = minSampleRaw ? Math.max(1, Math.min(500, parseInt(minSampleRaw, 10) || 1)) : 1
  const minAverage = minAverageRaw ? Math.max(0, Math.min(5, parseFloat(minAverageRaw) || 0)) : undefined

  const debouncedSearch = useDebounce(search, SEARCH_DEBOUNCE_MS)
  const activeSearch = debouncedSearch.trim()

  const {
    items,
    total,
    coverage,
    isPending,
    isFetchingMore,
    isError,
    hasMore,
    loadMore,
    refetch,
  } = useCreatorsList({ search: activeSearch || undefined, sort, role: role || undefined, min_sample: minSample, min_average: minAverage, unread })

  const hasItems = items.length > 0
  // #2775 reports metadata coverage per selection; a lower bound must never be
  // presented as an exhaustive library.
  const ratingsPartial = coverage != null && !coverage.ratings_complete
  const showFirstLoadError = isError && !hasItems
  const showMoreError = isError && hasItems

  return (
    <div className="mx-auto w-full max-w-5xl px-4 md:px-6">
      <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
        Creators
      </p>
      <h1 className="mt-1 text-xl font-bold md:text-2xl" style={{ color: 'var(--theme-text-primary)' }}>
        Creators you rated
      </h1>

      <section aria-labelledby="creators-controls-heading" className="mt-4 rounded-2xl border p-4 md:p-6" style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
        <h2 id="creators-controls-heading" className="sr-only">
          Browse your rated creators
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0">
            <label htmlFor="creators-search" className="text-xs font-semibold" style={{ color: 'var(--theme-text-muted)' }}>
              Search creators by name
            </label>
            <input
              id="creators-search"
              type="search"
              value={search}
              onChange={(event) => {
                const next = new URLSearchParams(searchParams)
                if (event.target.value.trim()) {
                  next.set('search', event.target.value.trim())
                } else {
                  next.delete('search')
                }
                next.delete('offset')
                setSearchParams(next)
              }}
              maxLength={100}
              className="form-control mt-1 w-full rounded-xl px-3 py-2.5 text-base md:text-sm"
            />
          </div>
          <div>
            <label htmlFor="creators-sort" className="text-xs font-semibold" style={{ color: 'var(--theme-text-muted)' }}>
              Sort
            </label>
            <select
              id="creators-sort"
              value={sort}
              onChange={(event) => {
                if (isCreatorListSort(event.target.value)) {
                  const next = new URLSearchParams(searchParams)
                  next.set('sort', event.target.value)
                  next.delete('offset')
                  setSearchParams(next)
                }
              }}
              className="form-control mt-1 w-full rounded-xl px-3 py-2.5 text-base md:text-sm sm:w-auto"
            >
              {SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4">
          <div>
            <label htmlFor="creators-role" className="text-xs font-semibold" style={{ color: 'var(--theme-text-muted)' }}>
              Role
            </label>
            <select
              id="creators-role"
              value={role}
              onChange={(event) => {
                const next = new URLSearchParams(searchParams)
                if (event.target.value.trim()) {
                  next.set('role', event.target.value.trim())
                } else {
                  next.delete('role')
                }
                next.delete('offset')
                setSearchParams(next)
              }}
              className="form-control mt-1 w-full rounded-xl px-3 py-2.5 text-base md:text-sm"
            >
              <option value="">Any role</option>
              <option value="writer">Writer</option>
              <option value="artist">Artist</option>
              <option value="penciler">Penciler</option>
              <option value="inker">Inker</option>
              <option value="colorist">Colorist</option>
              <option value="letterer">Letterer</option>
            </select>
          </div>
          <div>
            <label htmlFor="creators-min-sample" className="text-xs font-semibold" style={{ color: 'var(--theme-text-muted)' }}>
              Min rated issues
            </label>
            <input
              id="creators-min-sample"
              type="number"
              min={1}
              max={500}
              value={minSample}
              onChange={(event) => {
                const v = parseInt(event.target.value, 10)
                const next = new URLSearchParams(searchParams)
                if (!isNaN(v) && v > 1) {
                  next.set('min_sample', String(v))
                } else {
                  next.delete('min_sample')
                }
                next.delete('offset')
                setSearchParams(next)
              }}
              className="form-control mt-1 w-full rounded-xl px-3 py-2.5 text-base md:text-sm"
            />
          </div>
          <div>
            <label htmlFor="creators-min-average" className="text-xs font-semibold" style={{ color: 'var(--theme-text-muted)' }}>
              Min average ★
            </label>
            <input
              id="creators-min-average"
              type="number"
              step={0.1}
              min={0}
              max={5}
              value={minAverage !== undefined ? minAverage.toFixed(1) : ''}
              onChange={(event) => {
                const v = parseFloat(event.target.value)
                const next = new URLSearchParams(searchParams)
                if (!isNaN(v) && v > 0) {
                  next.set('min_average', String(v))
                } else {
                  next.delete('min_average')
                }
                next.delete('offset')
                setSearchParams(next)
              }}
              className="form-control mt-1 w-full rounded-xl px-3 py-2.5 text-base md:text-sm"
            />
          </div>
          <div className="flex items-end">
            <label className="flex items-center gap-2 text-xs font-semibold" style={{ color: 'var(--theme-text-muted)' }}>
              <input
                type="checkbox"
                checked={unread}
                onChange={(event) => {
                  const next = new URLSearchParams(searchParams)
                  if (event.target.checked) {
                    next.set('unread', 'true')
                  } else {
                    next.delete('unread')
                  }
                  next.delete('offset')
                  setSearchParams(next)
                }}
                className="h-4 w-4 rounded border"
                style={{ borderColor: 'var(--theme-border)', accentColor: 'var(--theme-personal-accent)' }}
              />
              Unread work
            </label>
          </div>
        </div>
      </section>

      {showFirstLoadError ? (
        <div role="alert" className="mt-6 rounded-2xl border p-4 md:p-6" style={{ borderColor: 'var(--theme-danger)' }}>
          <p className="text-sm font-bold" style={{ color: 'var(--theme-text-primary)' }}>
            Could not load your creators
          </p>
          <p className="mt-1 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
            Your data is unchanged. Please try again.
          </p>
          <button
            type="button"
            onClick={refetch}
            className="mt-4 min-h-11 rounded-lg px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            style={{ backgroundColor: 'var(--theme-primary-action)', color: 'var(--theme-text-primary)' }}
          >
            Try again
          </button>
        </div>
      ) : isPending ? (
        <div aria-label="Loading creators" className="mt-6 space-y-2">
          {[0, 1, 2, 3].map((row) => (
            <div key={row} className="h-14 animate-pulse rounded-xl" style={{ backgroundColor: 'var(--theme-bg-panel)' }} />
          ))}
        </div>
      ) : (
        <section aria-labelledby="creators-results-heading" className="mt-6">
          <h2 id="creators-results-heading" className="text-base font-bold md:text-lg" style={{ color: 'var(--theme-text-primary)' }}>
            Your rated creators
          </h2>

          {ratingsPartial && (
            <p className="mt-1 text-xs" style={{ color: 'var(--theme-text-muted)' }} role="note">
              Partial list: some rated issues are still missing creator metadata. Counts shown are lower
              bounds, not exhaustive totals.
            </p>
          )}

          {hasItems ? (
            <>
              <p className="mt-1 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
                Showing {items.length} of {total} creators
              </p>
              <ul className="mt-2 space-y-2">
                {items.map((item) => (
                  <CreatorRow key={item.canonical_creator_key} item={item} />
                ))}
              </ul>
            </>
          ) : (search || role || minSample > 1 || (minAverage !== undefined && minAverage > 0) || unread) ? (
            <p className="mt-2 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
              No creators match these filters.
            </p>
          ) : (
            <p className="mt-2 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
              No rated creators yet. Rating an issue adds its creators here.
            </p>
          )}

          {showMoreError && (
            <p role="alert" className="mt-4 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
              Could not load more creators. Creators already listed are still shown.
            </p>
          )}

          {hasMore && (
            <button
              type="button"
              onClick={() => {
                void loadMore()
              }}
              disabled={isFetchingMore}
              className="mt-4 min-h-11 w-full rounded-xl border px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] disabled:opacity-60 sm:w-auto"
              style={{ borderColor: 'var(--theme-border)', color: 'var(--theme-text-primary)' }}
            >
              {isFetchingMore ? 'Loading more…' : 'Load more'}
            </button>
          )}
        </section>
      )}
    </div>
  )
}
