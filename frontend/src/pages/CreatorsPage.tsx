import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useCreatorsList, CreatorListSelection } from '../hooks/useCreatorsList'
import type { CreatorListItem } from '../services/api-creators'

export default function CreatorsPage() {
  const [search, setSearch] = useState<string>('')
  const [sort, setSort] = useState<CreatorListSelection['sort']>('name')

  const selection: CreatorListSelection = {
    search: search.trim() || undefined,
    sort,
  }

  const {
    items,
    total,
    isPending,
    isError,
    error,
    refetch,
  } = useCreatorsList(selection)

  if (isPending) {
    return <div aria-label="Loading creators">Loading...</div>
  }

  if (isError) {
    return (
      <div role="alert">
        <p>Could not load your creators</p>
        <button onClick={refetch}>Try again</button>
      </div>
    )
  }

  const displaySearch = selection.search
  const hasItems = items.length > 0

  if (!hasItems && !displaySearch) {
    return <p>No rated creators yet. Rating an issue adds its creators here.</p>
  }

  if (!hasItems && displaySearch) {
    return <p>No creators match “{displaySearch}”.</p>
  }

  return (
    <div>
      <div>
        <label htmlFor="search">Search creators by name</label>
        <input
          id="search"
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <label htmlFor="sort">Sort</label>
        <select
          id="sort"
          value={sort}
          onChange={(e) => setSort(e.target.value as any)}
        >
          <option value="name">name</option>
          <option value="ratings_count">ratings_count</option>
          <option value="average_rating">average_rating</option>
        </select>
      </div>

      <p>Showing {items.length} of {total} creators</p>
      <ul>
        {items.map((creator: CreatorListItem) => {
          const roles = creator.normalized_roles.join(', ')
          const ratingCount = creator.ratings_count
          const avg = creator.average_rating
          const avgText = avg === null || avg === undefined ? 'unrated' : `${avg}★`
          const link = creator.canonical_creator_key?.includes('creator:')
          const key = creator.canonical_creator_key
          const content = (
            <div>
              <h3>{creator.display_name}</h3>
              <p>{roles}</p>
              <p>{ratingCount} rated issue{ratingCount === 1 ? '' : 's'}</p>
              <p>{avgText}</p>
            </div>
          )
          return (
            <li key={key}>
              {link ? (
                <Link to={`/creators/${encodeURIComponent(key)}`}>{content}</Link>
              ) : content}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
