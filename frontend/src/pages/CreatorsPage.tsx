import { useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { creatorsApi, type CreatorListItem, type CreatorListResponse } from '../services/api-creators'
import { queryKeys } from '../query/queryKeys'
import { useResponsive } from '../utils/responsive'
import { useDebounce } from '../hooks/useDebounce'

export default function CreatorsPage() {
  const { isMobile } = useResponsive()
  const [searchQuery, setSearchQuery] = useState('')
  const [sortBy, setSortBy] = useState<'name' | 'ratings_count' | 'average_rating'>('name')
  const [currentPage, setCurrentPage] = useState(0)
  const debouncedSearch = useDebounce(searchQuery, 300)

  const pageSize = isMobile ? 20 : 30

  const { data, isPending, isLoadingMore, hasMore, loadMore, error } = useQuery({
    queryKey: queryKeys.creators.list({
      search: debouncedSearch || undefined,
      sort: sortBy,
      limit: pageSize,
      offset: currentPage * pageSize,
    }),
    queryFn: () => creatorsApi.getList({
      search: debouncedSearch || undefined,
      sort: sortBy,
      limit: pageSize,
      offset: currentPage * pageSize,
    }),
    keepPreviousData: true,
    staleTime: 30 * 1000,
    refetchOnWindowFocus: false,
  })

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchQuery(e.target.value)
    setCurrentPage(0) // Reset to first page when searching
  }

  const handleSortChange = (newSort: 'name' | 'ratings_count' | 'average_rating') => {
    setSortBy(newSort)
    setCurrentPage(0) // Reset to first page when sorting
  }

  const handleLoadMore = () => {
    if (hasMore && !isLoadingMore) {
      setCurrentPage(prev => prev + 1)
    }
  }

  const sortedAndFilteredData = useMemo(() => {
    if (!data) return { items: [], total: 0 }

    // The backend already handles sorting, so this is just for safety
    let items = [...data.items]

    // Additional filtering if needed (though backend handles most of this)
    if (debouncedSearch) {
      items = items.filter(item =>
        item.display_name.toLowerCase().includes(debouncedSearch.toLowerCase())
      )
    }

    return {
      items,
      total: data.total,
    }
  }, [data, debouncedSearch])

  const totalPages = Math.ceil(sortedAndFilteredData.total / pageSize)

  if (isPending && !data) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mx-auto"></div>
          <p className="mt-2 text-sm text-gray-600">Loading creators...</p>
        </div>
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="space-y-6 md:space-y-8 pb-20">
        <header className="flex flex-wrap items-end justify-between gap-3 px-2">
          <div>
            <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow uppercase leading-none">Creators</h1>
            <p className="mt-2 text-[10px] font-bold text-stone-500 uppercase tracking-widest">Browse your rated creators</p>
          </div>
        </header>
        <div className="text-center text-red-500">Failed to load creators</div>
      </div>
    )
  }

  if (!data || sortedAndFilteredData.items.length === 0) {
    return (
      <div className="space-y-6 md:space-y-8 pb-20">
        <header className="flex flex-wrap items-end justify-between gap-3 px-2">
          <div>
            <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow uppercase leading-none">Creators</h1>
            <p className="mt-2 text-[10px] font-bold text-stone-500 uppercase tracking-widest">Browse your rated creators</p>
          </div>
        </header>
        <div className="text-center text-stone-500">
          {searchQuery ? 'No creators found matching your search.' : 'You haven&apos;t rated any creators yet.'}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6 md:space-y-8 pb-20">
      <header className="flex flex-wrap items-end justify-between gap-3 px-2">
        <div>
          <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow uppercase leading-none">Creators</h1>
          <p className="mt-2 text-[10px] font-bold text-stone-500 uppercase tracking-widest">
            Browse your rated creators ({sortedAndFilteredData.total} total)
          </p>
        </div>
      </header>

      {/* Search and Sort Controls */}
      <div className="space-y-4 px-2">
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1">
            <input
              type="text"
              placeholder="Search creators..."
              value={searchQuery}
              onChange={handleSearchChange}
              className="w-full px-3 py-2 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-lg text-[var(--theme-text-primary)] placeholder-[var(--theme-text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => handleSortChange('name')}
              className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                sortBy === 'name'
                  ? 'bg-[var(--theme-bg-active)] text-[var(--theme-text-primary)]'
                  : 'bg-[var(--theme-bg-panel)] text-[var(--theme-text-muted)] hover:bg-[var(--theme-bg-hover)]'
              }`}
            >
              Name
            </button>
            <button
              onClick={() => handleSortChange('ratings_count')}
              className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                sortBy === 'ratings_count'
                  ? 'bg-[var(--theme-bg-active)] text-[var(--theme-text-primary)]'
                  : 'bg-[var(--theme-bg-panel)] text-[var(--theme-text-muted)] hover:bg-[var(--theme-bg-hover)]'
              }`}
            >
              Most Rated
            </button>
            <button
              onClick={() => handleSortChange('average_rating')}
              className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                sortBy === 'average_rating'
                  ? 'bg-[var(--theme-bg-active)] text-[var(--theme-text-primary)]'
                  : 'bg-[var(--theme-bg-panel)] text-[var(--theme-text-muted)] hover:bg-[var(--theme-bg-hover)]'
              }`}
            >
              Highest Rated
            </button>
          </div>
        </div>
      </div>

      {/* Creator List */}
      <div className="space-y-2 px-2">
        {sortedAndFilteredData.items.map((creator) => (
          <Link
            key={creator.canonical_creator_key}
            to={`/creators/${encodeURIComponent(creator.canonical_creator_key)}`}
            className="block p-4 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-lg hover:bg-[var(--theme-bg-hover)] transition-colors"
          >
            <div className="flex items-center justify-between">
              <div className="flex-1 min-w-0">
                <h3 className="text-lg font-semibold text-[var(--theme-text-primary)] truncate">
                  {creator.display_name}
                </h3>
                <div className="flex flex-wrap gap-2 mt-1">
                  {creator.normalized_roles.length > 0 && (
                    <span className="text-xs text-[var(--theme-text-muted)] bg-[var(--theme-bg-active)] px-2 py-1 rounded">
                      {creator.normalized_roles.join(', ')}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex flex-col items-end ml-4 text-right">
                <div className="text-sm text-[var(--theme-text-primary)] font-medium">
                  {creator.ratings_count} {creator.ratings_count === 1 ? 'issue' : 'issues'}
                </div>
                {creator.average_rating !== null && (
                  <div className="text-xs text-[var(--theme-text-muted)] mt-1">
                    ★ {creator.average_rating.toFixed(1)}
                  </div>
                )}
              </div>
            </div>
          </Link>
        ))}
      </div>

      {/* Load More Button */}
      {hasMore && (
        <div className="flex justify-center px-2">
          <button
            onClick={handleLoadMore}
            disabled={isLoadingMore}
            className="px-4 py-2 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-lg text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isLoadingMore ? 'Loading...' : 'Load More'}
          </button>
        </div>
      )}

      {/* Page Info */}
      {totalPages > 1 && (
        <div className="text-center text-xs text-[var(--theme-text-muted)] px-2">
          Page {currentPage + 1} of {totalPages}
        </div>
      )}
    </div>
  )
}