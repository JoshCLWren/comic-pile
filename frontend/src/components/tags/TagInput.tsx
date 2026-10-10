import React, { useState, useMemo, useRef, useEffect, useCallback } from 'react'
import OverlayPortal from '../OverlayPortal'
import { TagChip } from './TagChip'
import type { Tag } from '../../types'
import { useTags, useCreateTag } from '../../hooks/useTags'
import { DEFAULT_TAG_COLOR_NAME, resolveTagColorHex } from '../../utils/tagColors'

interface TagInputProps {
  selectedTags: Tag[]
  onTagsChange: (tags: Tag[]) => void
  placeholder?: string
  className?: string
  disabled?: boolean
  maxTags?: number
  showCreateOption?: boolean
  /** Restricts new-tag creation to private tags; global creation is admin-only. */
  scope?: 'global' | 'private'
}

/** An existing tag the user can pick, or the inline "create this name" row. */
type TagOption = { isNew: false; tag: Tag } | { isNew: true; name: string }

/**
 * Levenshtein distance, used only to surface likely global matches.
 *
 * Mirrors the server's near-match suggestion so the client preview agrees with
 * what `create_tag` would return; the server remains authoritative.
 *
 * @param left - First string.
 * @param right - Second string.
 * @returns The edit distance between the two strings.
 */
function editDistance(left: string, right: string): number {
  const rows = left.length + 1
  const columns = right.length + 1
  let previous = Array.from({ length: columns }, (_value, index) => index)

  for (let row = 1; row < rows; row += 1) {
    const current = [row]
    for (let column = 1; column < columns; column += 1) {
      const substitutionCost = left[row - 1] === right[column - 1] ? 0 : 1
      current[column] = Math.min(
        current[column - 1] + 1,
        previous[column] + 1,
        previous[column - 1] + substitutionCost,
      )
    }
    previous = current
  }

  return previous[columns - 1]
}

/**
 * A tag picker with inline private-tag creation.
 *
 * Options come from the viewer's visible tag list. Selecting a tag that is
 * already assigned but not yet in `selectedTags` is prevented so the picker
 * cannot produce duplicate assignments.
 */
export function TagInput({
  selectedTags,
  onTagsChange,
  placeholder = 'Add tags...',
  className = '',
  disabled = false,
  maxTags,
  showCreateOption = true,
  scope = 'private',
}: TagInputProps) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const { data: visibleTags = [] } = useTags()
  const createTagMutation = useCreateTag()

  const selectedIds = useMemo(
    () => new Set(selectedTags.map((tag) => tag.id)),
    [selectedTags],
  )

  const atCapacity = Boolean(maxTags && selectedTags.length >= maxTags)

  const nearMatches = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    if (!normalizedQuery) {
      return []
    }

    return visibleTags
      .filter((tag) => tag.scope === 'global' && !selectedIds.has(tag.id))
      .map((tag) => ({ tag, distance: editDistance(tag.normalized_name, normalizedQuery) }))
      .filter(({ distance }) => distance > 0 && distance <= 2)
      .sort((left, right) => left.distance - right.distance)
      .slice(0, 3)
  }, [query, visibleTags, selectedIds])

  const matches = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    if (!normalizedQuery) {
      return []
    }

    const nearMatchIds = new Set(nearMatches.map(({ tag }) => tag.id))
    return visibleTags
      .filter(
        (tag) =>
          !selectedIds.has(tag.id) &&
          !nearMatchIds.has(tag.id) &&
          tag.normalized_name.includes(normalizedQuery),
      )
      .slice(0, 10)
  }, [query, visibleTags, selectedIds, nearMatches])

  /**
   * An exact normalized name always reuses the existing visible tag, so a
   * duplicate private tag is never offered or created.
   */
  const exactMatch = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    if (!normalizedQuery) {
      return undefined
    }
    return visibleTags.find((tag) => tag.normalized_name === normalizedQuery)
  }, [query, visibleTags])

  const canCreateNewTag =
    showCreateOption &&
    Boolean(query.trim()) &&
    !exactMatch &&
    !atCapacity &&
    !createTagMutation.isPending

  const options: TagOption[] = useMemo(() => {
    const rows: TagOption[] = [
      ...nearMatches.map(({ tag }) => ({ isNew: false as const, tag })),
      ...matches.map((tag) => ({ isNew: false as const, tag })),
    ]

    if (canCreateNewTag) {
      rows.push({ isNew: true, name: query.trim() })
    }

    return rows
  }, [nearMatches, matches, canCreateNewTag, query])

  const existingOptionCount = nearMatches.length + matches.length

  const closeMenu = useCallback(() => setOpen(false), [])

  const handleSelect = useCallback(
    (option: TagOption) => {
      if (option.isNew) {
        createTagMutation.mutate(
          {
            name: option.name,
            scope,
            color: DEFAULT_TAG_COLOR_NAME,
            include_near_matches: true,
          },
          {
            onSuccess: (created) => {
              onTagsChange([...selectedTags, created])
              setQuery('')
              closeMenu()
            },
          },
        )
        return
      }

      if (atCapacity || selectedIds.has(option.tag.id)) {
        return
      }

      onTagsChange([...selectedTags, option.tag])
      setQuery('')
      closeMenu()
    },
    [atCapacity, closeMenu, createTagMutation, onTagsChange, scope, selectedIds, selectedTags],
  )

  const handleRemove = useCallback(
    (tagToRemove: Tag) => {
      onTagsChange(selectedTags.filter((tag) => tag.id !== tagToRemove.id))
    },
    [onTagsChange, selectedTags],
  )

  useEffect(() => {
    if (!open) {
      return
    }

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target
      if (!(target instanceof Node)) {
        return
      }
      // The menu is portaled outside this container, so both roots count as "inside".
      if (containerRef.current?.contains(target) || menuRef.current?.contains(target)) {
        return
      }
      closeMenu()
    }

    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [closeMenu, open])

  useEffect(() => {
    if (atCapacity && query) {
      closeMenu()
    }
  }, [atCapacity, closeMenu, query])

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      {selectedTags.length > 0 && (
        <div className="flex flex-wrap items-center gap-1 rounded-t-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-2 py-1.5">
          {selectedTags.map((tag) => (
            <span key={tag.id} className="inline-flex items-center">
              <TagChip tag={tag} />
              <button
                type="button"
                aria-label={`Remove ${tag.name}`}
                className="ml-1 text-stone-500 hover:text-stone-200 transition-colors"
                onClick={() => handleRemove(tag)}
              >
                <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
                  <path
                    fillRule="evenodd"
                    d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293-4.293a1 1 0 01-1.414 1.414L10 11.414l4.293-4.293a1 1 0 010-1.414z"
                    clipRule="evenodd"
                  />
                </svg>
              </button>
            </span>
          ))}
        </div>
      )}

      <input
        ref={inputRef}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        aria-label={placeholder}
        value={query}
        disabled={disabled || atCapacity}
        onChange={(event) => setQuery(event.target.value)}
        onFocus={() => setOpen(true)}
        placeholder={placeholder}
        className={`form-control w-full rounded-lg px-3 py-2 text-sm ${
          selectedTags.length > 0 ? 'rounded-t-none border-t-0' : ''
        } ${disabled || atCapacity ? 'opacity-60 cursor-not-allowed' : ''}`}
      />

      {open && query.trim() && !atCapacity && (
        <OverlayPortal layer="menu">
          <div ref={menuRef} className="fixed left-4 right-4 top-24 z-50 max-h-72 overflow-y-auto surface-panel shadow-xl">
            {options.length === 0 && (
              <p className="px-3 py-2 text-sm text-stone-400">No tags found</p>
            )}

            {options.length > 0 && (
              <>
                {existingOptionCount === 0 && (
                  <p className="px-3 py-2 text-sm text-stone-400">No existing tags match</p>
                )}
                <ul role="listbox" className="py-1">
                  {options.map((option) => (
                    <li key={option.isNew ? 'create' : option.tag.id}>
                      <button
                        type="button"
                        role="option"
                        aria-selected={false}
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-stone-200 hover:bg-white/5 transition-colors"
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => handleSelect(option)}
                      >
                        {option.isNew ? (
                          <>
                            <span
                              className="w-3 h-3 rounded-full flex-shrink-0"
                              style={{
                                backgroundColor: resolveTagColorHex(DEFAULT_TAG_COLOR_NAME),
                              }}
                            />
                            <span className="truncate">{`Create "${option.name}"`}</span>
                            <span className="ml-auto text-xs font-semibold text-[var(--theme-comic-accent)]">
                              New
                          </span>
                        </>
                      ) : (
                        <>
                          <span
                            className="w-3 h-3 rounded-full flex-shrink-0"
                            style={{ backgroundColor: resolveTagColorHex(option.tag.color) }}
                          />
                          <span className="truncate">{option.tag.name}</span>
                          {option.tag.scope === 'global' && (
                            <span className="ml-auto text-xs text-stone-500">Global</span>
                          )}
                        </>
                      )}
                    </button>
                  </li>
                ))}
                </ul>
              </>
            )}

            {nearMatches.length > 0 && (
              <p className="px-3 py-1.5 border-t border-[var(--theme-border)] text-xs text-stone-500">
                Similar global tags exist. Pick one instead of creating a near-duplicate.
              </p>
            )}

            {createTagMutation.isError && (
              <p className="px-3 py-2 border-t border-[var(--theme-border)] text-xs text-[var(--theme-danger)]">
                Could not create that tag.
              </p>
            )}
          </div>
        </OverlayPortal>
      )}

      {atCapacity && maxTags && (
        <p className="mt-1 text-xs text-stone-500">Maximum {maxTags} tags allowed</p>
      )}
    </div>
  )
}