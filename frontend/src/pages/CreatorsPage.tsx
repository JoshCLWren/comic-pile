import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useDiscoveryModes, useDiscovery } from '../hooks/useCreatorDiscovery'
import { isNumber } from '../utils/runtimeChecks'
import type { DiscoveryMode } from '../services/api-creators'
import type { DiscoveryResultItem } from '../services/api-creators'
import { useCreatorsList } from '../hooks/useCreatorsList'
import type { CreatorListSort } from '../hooks/useCreatorsList'
import { useDebounce } from '../hooks/useDebounce'
import { useCreatorTeamChemistry } from '../hooks/useCreatorTeamChemistry'
import { creatorRoutePath, parseCreatorKey } from '../utils/creatorKey'
import type { CreatorListItem } from '../services/api-creators'
import CreatorTeamChemistrySection from '../components/CreatorTeamChemistrySection'

/** Quiet period before a typed name search becomes a new bounded query. */
const SEARCH_DEBOUNCE_MS = 300

/** Maximum number of creators that can be selected for comparison. */
const MAX_COMPARISON_SELECTION = 4

/** Discovery mode options (issue #3093). */
const DISCOVERY_MODE_OPTIONS: ReadonlyArray<{ value: DiscoveryMode; title: string; description: string }> = [
  { 
    value: 'consistently_loved', 
    title: 'Most Consistently Loved', 
    description: 'High average with consistent ratings'
  },
  { 
    value: 'polarizing', 
    title: 'Most Polarizing', 
    description: 'Broad range of ratings'
  },
  { 
    value: 'most_read', 
    title: 'Most Read', 
    description: 'Highest rated sample count'
  },
  { 
    value: 'highest_top_rating_rate', 
    title: 'Highest Top Rating Rate', 
    description: 'Highest percentage of 5-star ratings'
  },
  { 
    value: 'great_average_small_sample', 
    title: 'Great Average, Small Sample', 
    description: 'Promising with limited evidence'
  },
  { 
    value: 'loved_with_unread', 
    title: 'Loved with Unread', 
    description: 'Highly-rated with unread work'
  },
]

/**
 * Server-side browse orderings exposed by `GET /api/v1/creators`. Labels stay
 * human-readable; the option value is the wire contract from #2775.
 */
const SORT_OPTIONS: ReadonlyArray<{ value: CreatorListSort; label: string }> = [
  { value: 'name', label: 'Name (A to Z)' },
  { value: 'ratings_count', label: 'Most rated' },
  { value: 'average_rating', label: 'Highest average' },
]

/** Minimum rated-sample choices; values map to the server-side filter. */
const MIN_RATINGS_OPTIONS: ReadonlyArray<{ value: number; label: string }> = [
  { value: 0, label: 'Any' },
  { value: 3, label: '3+' },
  { value: 5, label: '5+' },
  { value: 10, label: '10+' },
  { value: 25, label: '25+' },
]

/** Sample sizes below this are visibly called out in the average column. */
const SMALL_SAMPLE_THRESHOLD = 5

function isCreatorListSort(value: string): value is CreatorListSort {
  return SORT_OPTIONS.some((option) => option.value === value)
}

function DiscoveryResultRow({
  item,
  isSelected,
  onToggle,
  selectionCount,
  maxSelection,
}: {
  item: DiscoveryResultItem
  isSelected: boolean
  onToggle: () => void
  selectionCount: number
  maxSelection: number
}) {
  const key = item.canonical_creator_key
  const parsedKey = parseCreatorKey(key)
  const detailPath = parsedKey ? creatorRoutePath(key) : null
  const roles = item.normalized_roles.join(', ')
  const ratingsCount = item.ratings_count
  const average = item.average_rating
  const canSelect = !isSelected && selectionCount < maxSelection

  // Format qualifying metrics for display
  const formatQualifyingMetric = (key: string, value: number | string) => {
    if (isNumber(value)) {
      if (key.includes('rate') || key.includes('score') || key.includes('percentage')) {
        return `${value}%`
      }
      if (key.includes('count') || key.includes('size') || key.includes('sample')) {
        return value.toString()
      }
      return value.toFixed(1)
    }
    return String(value)
  }

  const metricsDisplay = Object.entries(item.qualifying_metrics).map(([key, value]) => {
    const formattedValue = formatQualifyingMetric(key, value)
    return (
      <span key={key} className="text-xs font-medium" style={{ color: 'var(--theme-text-muted)' }}>
        {formattedValue}
      </span>
    )
  })

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
        {/* Display qualifying metrics */}
        <div className="flex flex-wrap gap-1">
          {metricsDisplay}
        </div>
        {item.upcoming_count > 0 && (
          <span className="text-xs" style={{ color: 'var(--theme-info)' }}>
            {item.upcoming_count} unread
          </span>
        )}
      </span>
    </>
  )

  const checkbox = (
    <input
      type="checkbox"
      checked={isSelected}
      onChange={onToggle}
      disabled={!canSelect}
      aria-label={`Select ${item.display_name} for comparison`}
      className="mt-1.5 h-4 w-4 rounded border-[var(--theme-border)] text-[var(--theme-primary-action)] focus:ring-2 focus:ring-[var(--theme-focus-ring)] disabled:opacity-50"
    />
  )

  return (
    <li className="min-w-0 rounded-xl border px-3 py-3 flex items-start gap-3" style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
      <div className="flex-shrink-0 self-center">{checkbox}</div>
      <div className="min-w-0 flex-1">
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
      </div>
    </li>
  )
}

function CreatorRow({
  item,
  isSelected,
  onToggle,
  selectionCount,
  maxSelection,
}: {
  item: CreatorListItem
  isSelected: boolean
  onToggle: () => void
  selectionCount: number
  maxSelection: number
}) {
  const key = item.canonical_creator_key
  const parsedKey = parseCreatorKey(key)
  const detailPath = parsedKey ? creatorRoutePath(key) : null
  const roles = item.normalized_roles.join(', ')
  const ratingsCount = item.ratings_count
  const average = item.average_rating
  const canSelect = !isSelected && selectionCount < maxSelection

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
        {average != null && ratingsCount < SMALL_SAMPLE_THRESHOLD && (
          <span className="font-semibold" style={{ color: 'var(--theme-warning)' }}>
            small sample
          </span>
        )}
      </span>
    </>
  )

  const checkbox = (
    <input
      type="checkbox"
      checked={isSelected}
      onChange={onToggle}
      disabled={!canSelect}
      aria-label={`Select ${item.display_name} for comparison`}
      className="mt-1.5 h-4 w-4 rounded border-[var(--theme-border)] text-[var(--theme-primary-action)] focus:ring-2 focus:ring-[var(--theme-focus-ring)] disabled:opacity-50"
    />
  )

  return (
    <li className="min-w-0 rounded-xl border px-3 py-2 flex items-start gap-3" style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
      <div className="flex-shrink-0 self-center">{checkbox}</div>
      <div className="min-w-0 flex-1">
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
      </div>
    </li>
  )
}

export default function CreatorsPage() {
  const [search, setSearch] = useState<string>('')
  const [sort, setSort] = useState<CreatorListSort>('name')
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set())
  const [minRatings, setMinRatings] = useState<number>(0)
  const [discoveryMode, setDiscoveryMode] = useState<DiscoveryMode | null>(null)
  const debouncedSearch = useDebounce(search, SEARCH_DEBOUNCE_MS)
  const activeSearch = debouncedSearch.trim()
  const navigate = useNavigate()

  // Regular browsing hooks
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
  } = useCreatorsList({ search: activeSearch || undefined, sort, minRatings: minRatings || undefined })
  const {
    data: teamChemistry,
    isError: teamChemistryError,
    refetch: refetchTeamChemistry,
  } = useCreatorTeamChemistry()

  const hasItems = items.length > 0

  // Discovery hooks
  const { isLoading: isLoadingDiscoveryModes } = useDiscoveryModes()
  const {
    data: discovery,
    isPending: isDiscoveryPending,
    isError: isDiscoveryError,
    refetch: refetchDiscovery,
  } = useDiscovery(
    {
      mode: discoveryMode || 'consistently_loved',
      limit: 20,
      offset: 0,
    },
    !!discoveryMode,
  )
  const ratingsPartial = coverage != null && !coverage.ratings_complete
  const showFirstLoadError = isError && !hasItems
  const showMoreError = isError && hasItems
  const selectionCount = selectedKeys.size
  const canCompare = selectionCount >= 2

  // Clear discovery mode when switching to regular browsing
  const handleSearchChange = (value: string) => {
    setSearch(value)
    if (value && discoveryMode) {
      setDiscoveryMode(null)
    }
  }

  const handleDiscoveryModeChange = (mode: DiscoveryMode | null) => {
    setDiscoveryMode(mode)
    if (mode) {
      setSearch('') // Clear search when switching to discovery
    }
  }

  const handleToggleSelection = (key: string) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else if (next.size < MAX_COMPARISON_SELECTION) {
        next.add(key)
      }
      return next
    })
  }

  const handleCompare = () => {
    if (canCompare) {
      const keys = Array.from(selectedKeys).join(',')
      navigate(`/creators/compare?keys=${encodeURIComponent(keys)}`)
    }
  }

  const handleClearSelection = () => {
    setSelectedKeys(new Set())
  }

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
        
        {/* Discovery mode selector */}
        <div className="mb-4">
          <label className="text-xs font-semibold" style={{ color: 'var(--theme-text-muted)' }}>
            Discovery Insights
          </label>
          <div className="mt-1 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => handleDiscoveryModeChange(null)}
              className={`min-h-10 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                !discoveryMode 
                  ? 'bg-[var(--theme-primary-action)] text-white' 
                  : 'bg-[var(--theme-bg-secondary)] text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)]'
              }`}
            >
              Browse Creators
            </button>
            
            {isLoadingDiscoveryModes ? (
              <div className="min-h-10 rounded-lg bg-[var(--theme-bg-secondary)] px-4 py-2 text-sm text-[var(--theme-text-muted)]">
                Loading insights...
              </div>
            ) : (
              DISCOVERY_MODE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => handleDiscoveryModeChange(option.value)}
                  className={`min-h-10 max-w-[200px] rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                    discoveryMode === option.value
                      ? 'bg-[var(--theme-primary-action)] text-white'
                      : 'bg-[var(--theme-bg-secondary)] text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)]'
                  }`}
                  title={option.description}
                >
                  <div className="truncate">{option.title}</div>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Regular browsing controls (hidden in discovery mode) */}
        {!discoveryMode && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_auto_auto]">
            <div className="min-w-0">
              <label htmlFor="creators-search" className="text-xs font-semibold" style={{ color: 'var(--theme-text-muted)' }}>
                Search creators by name
              </label>
              <input
                id="creators-search"
                type="search"
                value={search}
                onChange={(event) => handleSearchChange(event.target.value)}
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
                    setSort(event.target.value)
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
            <div>
              <label htmlFor="creators-min-ratings" className="text-xs font-semibold" style={{ color: 'var(--theme-text-muted)' }}>
                Minimum rated
              </label>
              <select
                id="creators-min-ratings"
                value={minRatings}
                onChange={(event) => setMinRatings(Number(event.target.value))}
                className="form-control mt-1 w-full rounded-xl px-3 py-2.5 text-base md:text-sm sm:w-auto"
              >
                {MIN_RATINGS_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}
      </section>

      {selectionCount > 0 && (
        <div className="mt-4 rounded-2xl border p-3 md:p-4 sticky top-16 z-10" style={{ borderColor: 'var(--theme-primary-action)', backgroundColor: 'var(--theme-primary-action)/5' }}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold" style={{ color: 'var(--theme-text-primary)' }}>
                {selectionCount} of {MAX_COMPARISON_SELECTION} selected for comparison
              </span>
              {canCompare && (
                <button
                  type="button"
                  onClick={handleCompare}
                  className="min-h-10 rounded-lg px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                  style={{ backgroundColor: 'var(--theme-primary-action)', color: 'var(--theme-text-primary)' }}
                >
                  Compare
                </button>
              )}
            </div>
            <button
              type="button"
              onClick={handleClearSelection}
              className="text-sm font-medium underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
              style={{ color: 'var(--theme-text-muted)' }}
            >
              Clear selection
            </button>
          </div>
        </div>
      )}

      {/* Discovery mode header */}
      {discoveryMode && discovery && (
        <section className="mt-4 rounded-2xl border p-4 md:p-6" style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <h2 className="text-lg font-bold" style={{ color: 'var(--theme-text-primary)' }}>
                {discovery.title}
              </h2>
              <p className="mt-1 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
                {discovery.description}
              </p>
              <p className="mt-2 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
                Showing {discovery.items.length} of {discovery.total} creators
              </p>
            </div>
            <button
              type="button"
              onClick={() => handleDiscoveryModeChange(null)}
              className="text-sm font-medium underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
              style={{ color: 'var(--theme-text-muted)' }}
            >
              Back to browse
            </button>
          </div>
        </section>
      )}

      {discoveryMode ? (
        isDiscoveryPending ? (
          <div aria-label="Loading discovery" className="mt-6 space-y-2">
            {[0, 1, 2, 3].map((row) => (
              <div key={row} className="h-14 animate-pulse rounded-xl" style={{ backgroundColor: 'var(--theme-bg-panel)' }} />
            ))}
          </div>
        ) : isDiscoveryError ? (
          <div role="alert" className="mt-6 rounded-2xl border p-4 md:p-6" style={{ borderColor: 'var(--theme-danger)' }}>
            <p className="text-sm font-bold" style={{ color: 'var(--theme-text-primary)' }}>
              Could not load discovery results
            </p>
            <p className="mt-1 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
              Your data is unchanged. Please try again.
            </p>
            <button
              type="button"
              onClick={() => { void refetchDiscovery() }}
              className="mt-4 min-h-11 rounded-lg px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
              style={{ backgroundColor: 'var(--theme-primary-action)', color: 'var(--theme-text-primary)' }}
            >
              Try again
            </button>
          </div>
        ) : (
          <section aria-labelledby="discovery-results-heading" className="mt-6">
            <h2 id="discovery-results-heading" className="text-base font-bold md:text-lg" style={{ color: 'var(--theme-text-primary)' }}>
              {discovery?.title ?? 'Discovery'}
            </h2>
            {discovery && discovery.items.length > 0 ? (
              <ul className="mt-2 space-y-2">
                {discovery.items.map((item) => (
                  <DiscoveryResultRow
                    key={item.canonical_creator_key}
                    item={item}
                    isSelected={selectedKeys.has(item.canonical_creator_key)}
                    onToggle={() => handleToggleSelection(item.canonical_creator_key)}
                    selectionCount={selectionCount}
                    maxSelection={MAX_COMPARISON_SELECTION}
                  />
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
                No creators match this discovery view yet.
              </p>
            )}
          </section>
        )
      ) : showFirstLoadError ? (
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
                  <CreatorRow
                    key={item.canonical_creator_key}
                    item={item}
                    isSelected={selectedKeys.has(item.canonical_creator_key)}
                    onToggle={() => handleToggleSelection(item.canonical_creator_key)}
                    selectionCount={selectionCount}
                    maxSelection={MAX_COMPARISON_SELECTION}
                  />
                ))}
              </ul>
            </>
          ) : activeSearch ? (
            <p className="mt-2 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
              No creators match “{activeSearch}”.
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
      {teamChemistry && <CreatorTeamChemistrySection data={teamChemistry} />}
      {teamChemistryError && (
        <p role="alert" className="mt-6 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          Could not load team chemistry. Your creators and ratings are unchanged.
          <button
            type="button"
            onClick={() => {
              void refetchTeamChemistry()
            }}
            className="ml-2 underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            style={{ color: 'var(--theme-text-primary)' }}
          >
            Try again
          </button>
        </p>
      )}
    </div>
  )
}
