import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useCreatorsList } from '../hooks/useCreatorsList'
import type { CreatorListSort } from '../hooks/useCreatorsList'
import { useDebounce } from '../hooks/useDebounce'
import { useCreatorTeamChemistry } from '../hooks/useCreatorTeamChemistry'
import { useCreatorDiscoveries } from '../hooks/useCreatorDiscoveries'
import { creatorRoutePath, parseCreatorKey } from '../utils/creatorKey'
import { SMALL_SAMPLE_THRESHOLD } from '../utils/creatorUtils'
import type { CreatorListItem } from '../services/api-creators'
import CreatorTeamChemistrySection from '../components/CreatorTeamChemistrySection'
import CreatorDiscoverySection from '../components/CreatorDiscoverySection'
import GlossaryLink from '../components/GlossaryLink'

/** Quiet period before a typed name search becomes a new bounded query. */
const SEARCH_DEBOUNCE_MS = 300

/** Maximum number of creators that can be selected for comparison. */
const MAX_COMPARISON_SELECTION = 4

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

/**
 * The two top-level modes of `/creators`: the plain directory and the optional
 * explainable taste-discovery exploration. Browse stays the default so the
 * straightforward directory is never replaced.
 */
type CreatorsViewMode = 'browse' | 'discover'

function isCreatorListSort(value: string): value is CreatorListSort {
  return SORT_OPTIONS.some((option) => option.value === value)
}

/**
 * Parse the durable `keys` query parameter into the selected creator set.
 *
 * The URL is the single source of truth for comparison selection so a browser
 * Back/forward round trip through `/creators/compare` repopulates the exact
 * same checkboxes (#3624). Keys are canonical creator identities, never display
 * names. Malformed keys are dropped, duplicates collapse, and the existing
 * maximum-selection rule caps the restored set without ever preventing a later
 * deselect.
 */
function parseSelectionKeys(rawKeys: string | null): Set<string> {
  const keys = new Set<string>()
  if (!rawKeys) return keys
  for (const candidate of rawKeys.split(',')) {
    const key = candidate.trim()
    if (!key || parseCreatorKey(key) === null) continue
    keys.add(key)
  }
  return keys
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
  const detailPath = parseCreatorKey(key) != null ? creatorRoutePath(key) : null
  const roles = item.normalized_roles.join(', ')
  const ratingsCount = item.ratings_count
  const average = item.average_rating
  // Selected checkboxes are always enabled (can be unchecked).
  // Unselected checkboxes are disabled only when at max selection.
  const canSelect = isSelected || selectionCount < maxSelection

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

  const [showSampleHelp, setShowSampleHelp] = useState(false)
  const helpId = useId()
  const sampleButtonRef = useRef<HTMLButtonElement>(null)

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

  const showSmallSample = average != null && ratingsCount < SMALL_SAMPLE_THRESHOLD

  /**
   * Help control lives outside the row's Link (#3627 review): a button
   * nested in a link is invalid and lets clicks navigate to the creator
   * instead of opening the explanation. Activation shows the explanation
   * inline for touch, pointer, and keyboard readers — hover is never required.
   * The panel stays in the document (hidden while collapsed) so `aria-controls`
   * always resolves, and Escape is handled at the group so it also works while
   * focus is on the glossary link inside the panel.
   */
  const sampleHelp = showSmallSample ? (
    <div
      className="mt-1 flex flex-wrap items-start gap-x-2 text-xs"
      onKeyDown={(event) => {
        if (event.key === 'Escape' && showSampleHelp) {
          event.preventDefault()
          setShowSampleHelp(false)
          sampleButtonRef.current?.focus()
        }
      }}
    >
      <button
        ref={sampleButtonRef}
        type="button"
        className="-mx-1 inline-flex min-h-6 items-center rounded px-1 font-semibold underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
        style={{ color: 'var(--theme-warning)' }}
        aria-expanded={showSampleHelp}
        aria-controls={helpId}
        aria-label={`Small sample: fewer than ${SMALL_SAMPLE_THRESHOLD} rated comics. Average ratings based on a small sample may be less representative.`}
        onClick={() => setShowSampleHelp((open) => !open)}
      >
        small sample
      </button>
      <span
        id={helpId}
        hidden={!showSampleHelp}
        className="mt-0.5 basis-full break-words"
        style={{ color: 'var(--theme-text-muted)' }}
      >
        Fewer than {SMALL_SAMPLE_THRESHOLD} rated comics (distinct comics you have
        rated — not read items or credited roles). Average ratings based on a small
        sample may be less representative. This is a confidence/context indicator,
        not a data-quality defect or a new rating-scoring formula.{' '}
        <GlossaryLink id="small-sample">Glossary</GlossaryLink>
      </span>
    </div>
  ) : null

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
        {sampleHelp}
      </div>
    </li>
  )
}

/**
 * Segmented control switching between the plain creator directory and the
 * optional taste-discovery exploration mode. A pressed-button group (not a
 * nested tablist) keeps the discovery section's own category tabs unambiguous.
 */
function ViewModeToggle({
  mode,
  onChange,
}: {
  mode: CreatorsViewMode
  onChange: (mode: CreatorsViewMode) => void
}) {
  const options: ReadonlyArray<{ value: CreatorsViewMode; label: string }> = [
    { value: 'browse', label: 'Browse' },
    { value: 'discover', label: 'Discover' },
  ]
  return (
    <div role="group" aria-label="Creators view mode" className="mt-3 inline-flex flex-wrap gap-2">
      {options.map((option) => {
        const isActive = option.value === mode
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={isActive}
            onClick={() => onChange(option.value)}
            className="min-h-10 rounded-full border px-4 py-2 text-sm font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            style={
              isActive
                ? {
                    borderColor: 'var(--theme-primary-action)',
                    backgroundColor: 'var(--theme-primary-action)',
                    color: 'var(--theme-text-primary)',
                  }
                : {
                    borderColor: 'var(--theme-border)',
                    color: 'var(--theme-text-muted)',
                  }
            }
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

export default function CreatorsPage() {
  const [search, setSearch] = useState<string>('')
  const [sort, setSort] = useState<CreatorListSort>('name')
  const [minRatings, setMinRatings] = useState<number>(0)
  const [viewMode, setViewMode] = useState<CreatorsViewMode>('browse')
  const debouncedSearch = useDebounce(search, SEARCH_DEBOUNCE_MS)
  const activeSearch = debouncedSearch.trim()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  // Restoring from the URL (a `Change selection` link, a browser Back/forward
  // round trip, or a reload) derives the checkbox set directly from `?keys=`.
  // Deriving instead of mirroring in state keeps the URL authoritative and
  // avoids a restore effect that could overwrite a reader's toggle with a
  // stale URL snapshot.
  // Rewrite only the `keys` parameter so any other context on the URL survives.
  const updateSelectionUrl = useCallback(
    (keys: Set<string>) => {
      setSearchParams(
        (previous) => {
          const next = new URLSearchParams(previous)
          if (keys.size > 0) {
            next.set('keys', Array.from(keys).join(','))
          } else {
            next.delete('keys')
          }
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

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
  // Discovery is an optional exploration mode, so it only queries once visible.
  const {
    data: discoveries,
    isPending: discoveriesPending,
    isError: discoveriesError,
    refetch: refetchDiscoveries,
  } = useCreatorDiscoveries(viewMode === 'discover')

  const parsedSelectionKeys = useMemo(
    () => parseSelectionKeys(searchParams.get('keys')),
    [searchParams],
  )

  // Selections are validated against the creators actually present in the
  // loaded list, so duplicate or unknown/stale keys cannot inflate the
  // counter or consume selection slots (#4208). The four-creator cap applies
  // to the visible selection only: a key that isn't on the current page never
  // occupies a slot, so an unknown key in the URL can't crowd out a valid one.
  const selectedKeys = useMemo(() => {
    const visible = new Set(items.map((item) => item.canonical_creator_key))
    const filtered = new Set<string>()
    for (const key of parsedSelectionKeys) {
      if (visible.has(key) && filtered.size < MAX_COMPARISON_SELECTION) {
        filtered.add(key)
      }
    }
    return filtered
  }, [parsedSelectionKeys, items])

  // Keep the durable `keys` URL canonical: collapse repeated identities, trim
  // stray whitespace, and drop keys that fail creator-key syntax. A valid key is
  // never deleted merely because its row is not on the loaded page (a creator on
  // page 2, or one filtered out by search), so a saved selection survives list
  // changes, a reload, and a Back/forward round trip (#4208). Unknown but
  // well-formed keys also stay in the URL because this page cannot confirm they
  // are not real creators elsewhere in the list; they never occupy a selection
  // slot because the cap above applies to visible creators only.
  useEffect(() => {
    const rawKeys = searchParams.get('keys')
    if (!rawKeys) return
    const valid = parseSelectionKeys(rawKeys)
    const canonical = Array.from(valid).join(',')
    // Compare the serialized form (not a sorted set) so the rewrite happens once
    // and lands on exactly the value `updateSelectionUrl` would write back.
    if (rawKeys !== canonical) {
      updateSelectionUrl(valid)
    }
  }, [searchParams, updateSelectionUrl])

  const hasItems = items.length > 0
  const ratingsPartial = coverage != null && !coverage.ratings_complete
  const showFirstLoadError = isError && !hasItems
  const showMoreError = isError && hasItems
  const selectionCount = selectedKeys.size
  const canCompare = selectionCount >= 2

  const handleToggleSelection = (key: string) => {
    // Start from every key the URL carries, not just the visible rows, so
    // toggling one checkbox never silently drops a valid selection whose row is
    // on another page or filtered out by the current search (#4208). Unknown or
    // off-page keys are preserved in the URL but never occupy a comparison
    // slot, so the four-creator cap is measured against the visible selection
    // only; otherwise a bogus key in the URL could crowd out a real one.
    const next = new Set(parsedSelectionKeys)
    if (next.has(key)) {
      // Selected checkboxes always stay enabled so one creator can be dropped.
      next.delete(key)
    } else if (selectedKeys.size < MAX_COMPARISON_SELECTION) {
      next.add(key)
    } else {
      return
    }
    updateSelectionUrl(next)
  }

  const handleCompare = () => {
    if (canCompare) {
      const keys = Array.from(selectedKeys).join(',')
      navigate(`/creators/compare?keys=${encodeURIComponent(keys)}`)
    }
  }

  const handleClearSelection = () => {
    updateSelectionUrl(new Set())
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-4 md:px-6">
      <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
        Creators
      </p>
      <h1 className="mt-1 text-xl font-bold md:text-2xl" style={{ color: 'var(--theme-text-primary)' }}>
        Creators you rated
      </h1>

      <ViewModeToggle mode={viewMode} onChange={setViewMode} />

      {viewMode === 'browse' && (
        <>
          <section aria-labelledby="creators-controls-heading" className="mt-4 rounded-2xl border p-4 md:p-6" style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
            <h2 id="creators-controls-heading" className="sr-only">
              Browse your rated creators
            </h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_auto_auto]">
              <div className="min-w-0">
                <label htmlFor="creators-search" className="text-xs font-semibold" style={{ color: 'var(--theme-text-muted)' }}>
                  Search creators by name
                </label>
                <input
                  id="creators-search"
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
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
        </>
      )}

      {viewMode === 'discover' && (
        <section aria-labelledby="creator-discovery-mode-heading" className="mt-6">
          <h2 id="creator-discovery-mode-heading" className="sr-only">
            Taste discovery
          </h2>
          {discoveriesError ? (
            <p role="alert" className="text-sm" style={{ color: 'var(--theme-text-muted)' }}>
              Could not load taste discoveries. Your creators and ratings are unchanged.
              <button
                type="button"
                onClick={() => {
                  void refetchDiscoveries()
                }}
                className="ml-2 underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                style={{ color: 'var(--theme-text-primary)' }}
              >
                Try again
              </button>
            </p>
          ) : discoveriesPending ? (
            <div aria-label="Loading discoveries" className="space-y-2">
              {[0, 1, 2].map((row) => (
                <div
                  key={row}
                  className="h-14 animate-pulse rounded-xl"
                  style={{ backgroundColor: 'var(--theme-bg-panel)' }}
                />
              ))}
            </div>
          ) : discoveries ? (
            <CreatorDiscoverySection data={discoveries} />
          ) : null}
        </section>
      )}
    </div>
  )
}
