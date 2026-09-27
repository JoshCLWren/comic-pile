import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useCreatorsList, type CreatorListSort } from '../hooks/useCreatorsList'
import { useDebounce } from '../hooks/useDebounce'
import { creatorRoutePath, parseCreatorKey } from '../utils/creatorKey'
import type { CreatorListItem } from '../services/api-creators'

const SORT_OPTIONS: ReadonlyArray<{ value: CreatorListSort; label: string }> = [
  { value: 'name', label: 'Name' },
  { value: 'ratings_count', label: 'Most rated' },
  { value: 'average_rating', label: 'Highest rated' },
]

const panelStyle = {
  borderColor: 'var(--theme-border)',
  backgroundColor: 'var(--theme-bg-panel)',
} as const

const inputStyle = {
  borderColor: 'var(--theme-border)',
  backgroundColor: 'var(--theme-bg-panel)',
  color: 'var(--theme-text-primary)',
} as const

function CreatorRowBody({ creator }: { creator: CreatorListItem }) {
  return (
    <>
      <span className="block min-w-0 truncate text-base font-bold" style={{ color: 'var(--theme-text-primary)' }}>
        {creator.display_name}
      </span>
      <span className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
        {creator.normalized_roles.length > 0 && (
          <span className="break-words">{creator.normalized_roles.join(', ')}</span>
        )}
        <span>
          {creator.ratings_count} {creator.ratings_count === 1 ? 'rated issue' : 'rated issues'}
        </span>
        {creator.average_rating != null ? (
          <span
            className="font-bold"
            style={{ color: 'var(--theme-personal-accent)' }}
            aria-label={`Your average rating ${creator.average_rating} out of 5`}
          >
            {creator.average_rating.toFixed(1)}★
          </span>
        ) : (
          <span>unrated</span>
        )}
      </span>
    </>
  )
}

function CreatorRow({ creator }: { creator: CreatorListItem }) {
  const isCanonical = parseCreatorKey(creator.canonical_creator_key) != null

  if (!isCanonical) {
    return (
      <li className="min-w-0 rounded-xl border px-3 py-2" style={panelStyle}>
        <CreatorRowBody creator={creator} />
      </li>
    )
  }

  return (
    <li className="min-w-0">
      <Link
        to={creatorRoutePath(creator.canonical_creator_key)}
        className="block min-w-0 rounded-xl border px-3 py-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
        style={panelStyle}
      >
        <CreatorRowBody creator={creator} />
      </Link>
    </li>
  )
}

export default function CreatorsPage() {
  const [searchInput, setSearchInput] = useState('')
  const [sortBy, setSortBy] = useState<CreatorListSort>('name')
  const debouncedSearch = useDebounce(searchInput, 300)
  const normalizedSearch = debouncedSearch.trim()

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
  } = useCreatorsList({ search: normalizedSearch || undefined, sort: sortBy })

  const ratingsPartial = coverage != null && !coverage.ratings_complete

  return (
    <div className="mx-auto w-full max-w-5xl px-4 md:px-6">
      <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
        Creators
      </p>
      <h1 className="mt-1 text-xl font-bold md:text-2xl" style={{ color: 'var(--theme-text-primary)' }}>
        Your rated creators
      </h1>
      <p className="mt-2 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
        Writers, artists, and other creators behind issues you rated, ordered from your own
        ratings.
      </p>

      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <label htmlFor="creator-search" className="sr-only">
            Search creators by name
          </label>
          <input
            id="creator-search"
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search creators by name"
            autoComplete="off"
            className="min-h-11 w-full rounded-xl border px-3 py-2.5 text-base focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] sm:text-sm"
            style={inputStyle}
          />
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="creator-sort" className="text-xs font-bold" style={{ color: 'var(--theme-text-muted)' }}>
            Sort
          </label>
          <select
            id="creator-sort"
            value={sortBy}
            onChange={(event) => setSortBy(event.target.value as CreatorListSort)}
            className="min-h-11 min-w-0 rounded-xl border px-3 py-2.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            style={inputStyle}
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {ratingsPartial && (
        <p className="mt-3 text-xs" style={{ color: 'var(--theme-text-muted)' }} role="note">
          Partial list: some rated issues are still missing creator metadata, so this is a lower
          bound rather than an exhaustive count.
        </p>
      )}

      {isPending ? (
        <div className="mt-4" aria-label="Loading creators">
          <div className="h-4 w-32 animate-pulse rounded" style={{ backgroundColor: 'var(--theme-bg-panel)' }} />
          <div className="mt-3 h-12 animate-pulse rounded-xl" style={{ backgroundColor: 'var(--theme-bg-panel)' }} />
          <div className="mt-2 h-12 animate-pulse rounded-xl" style={{ backgroundColor: 'var(--theme-bg-panel)' }} />
        </div>
      ) : isError && items.length === 0 ? (
        <div className="mt-4">
          <p role="alert" className="text-sm" style={{ color: 'var(--theme-text-muted)' }}>
            Could not load your creators. Your data is unchanged.
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
      ) : items.length === 0 ? (
        <p className="mt-4 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          {normalizedSearch
            ? `No creators match “${normalizedSearch}”.`
            : 'No rated creators yet. Rating an issue adds its creators here.'}
        </p>
      ) : (
        <>
          <p className="mt-4 text-xs" style={{ color: 'var(--theme-text-dim)' }}>
            Showing {items.length} of {total} {total === 1 ? 'creator' : 'creators'}
          </p>
          <ul className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {items.map((creator) => (
              <CreatorRow key={creator.canonical_creator_key} creator={creator} />
            ))}
          </ul>

          {isError && (
            <p role="alert" className="mt-4 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
              Could not load more creators. The creators already listed are still shown.
            </p>
          )}

          {hasMore && (
            <button
              type="button"
              onClick={() => { void loadMore() }}
              disabled={isFetchingMore}
              className="mt-4 min-h-11 w-full rounded-xl border px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] disabled:opacity-60 sm:w-auto"
              style={{ borderColor: 'var(--theme-border)', color: 'var(--theme-text-primary)' }}
            >
              {isFetchingMore ? 'Loading more…' : 'Load more'}
            </button>
          )}
        </>
      )}
    </div>
  )
}
