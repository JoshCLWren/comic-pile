import React, { useState, useEffect, useRef, useCallback } from 'react'
import { TagChip } from './TagChip'
import type { Tag, TagSearchResult } from '../../types'
import { useTagSearch, useTagNearMatches, useCheckTagNameAvailability, useCreateTag } from '../../hooks/useTags'

interface TagInputProps {
  selectedTags: Tag[]
  onTagsChange: (tags: Tag[]) => void
  onTagCreate?: (tag: Tag) => void
  placeholder?: string
  className?: string
  disabled?: boolean
  maxTags?: number
  showCreateOption?: boolean
  scope?: 'global' | 'private'
}

interface TagOption {
  id: number
  name: string
  color: string
  isGlobal: boolean
  isPrivate: boolean
  isNew?: boolean
}

export function TagInput({
  selectedTags,
  onTagsChange,
  onTagCreate,
  placeholder = 'Add tags...',
  className = '',
  disabled = false,
  maxTags,
  showCreateOption = true,
  scope = 'private',
}: TagInputProps) {
  const [query, setQuery] = useState('')
  const [showDropdown, setShowDropdown] = useState(false)
  const [isCreating, setIsCreating] = useState(false)
  const [newTagName, setNewTagName] = useState('')
  const [showNearMatches, setShowNearMatches] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Search for existing tags
  const { data: searchResults, isLoading: isSearching } = useTagSearch(query, 10)
  
  // Check for near matches when creating a new tag
  const { data: nearMatches, isLoading: isLoadingNearMatches } = useTagNearMatches(
    newTagName,
    5
  )
  
  // Check name availability
  const { data: nameAvailability } = useCheckTagNameAvailability(
    newTagName,
    scope
  )

  // Create tag mutation
  const createTagMutation = useCreateTag()

  // Filter available options
  const availableOptions = React.useMemo(() => {
    const options: TagOption[] = []

    // Add selected tags first
    selectedTags.forEach(tag => {
      options.push({
        id: tag.id,
        name: tag.name,
        color: tag.color,
        isGlobal: tag.scope === 'global',
        isPrivate: tag.scope === 'private',
      })
    })

    // Add search results (excluding already selected)
    if (searchResults) {
      searchResults.forEach(result => {
        if (!selectedTags.some(tag => tag.id === result.id)) {
          options.push({
            id: result.id,
            name: result.name,
            color: result.color,
            isGlobal: result.is_global,
            isPrivate: result.is_private,
          })
        }
      })
    }

    // Add near matches if creating a new tag
    if (isCreating && nearMatches && newTagName) {
      nearMatches.forEach(match => {
        if (!options.some(opt => opt.id === match.tag.id)) {
          options.push({
            id: match.tag.id,
            name: match.tag.name,
            color: match.tag.color,
            isGlobal: match.tag.scope === 'global',
            isPrivate: match.tag.scope === 'private',
          })
        }
      })
    }

    // Add "Create new" option
    if (showCreateOption && isCreating && newTagName && nameAvailability?.available) {
      options.push({
        id: Date.now(), // Temporary ID
        name: newTagName,
        color: '#DC2626', // Default red color
        isGlobal: scope === 'global',
        isPrivate: scope === 'private',
        isNew: true,
      })
    }

    // Remove duplicates by ID
    const uniqueOptions = options.filter((option, index, self) => 
      index === self.findIndex(opt => opt.id === option.id)
    )

    return uniqueOptions
  }, [selectedTags, searchResults, nearMatches, isCreating, newTagName, nameAvailability, showCreateOption, scope])

  // Handle input focus
  const handleFocus = useCallback(() => {
    setShowDropdown(true)
  }, [])

  // Handle input change
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value
    setQuery(value)
    setNewTagName(value)
    
    if (value.trim()) {
      setIsCreating(true)
      setShowNearMatches(true)
    } else {
      setIsCreating(false)
      setShowNearMatches(false)
    }
  }

  // Handle option selection
  const handleOptionSelect = (option: TagOption) => {
    if (maxTags && selectedTags.length >= maxTags) {
      return
    }

    if (option.isNew) {
      // Create new tag
      const newTag: Tag = {
        id: option.id,
        name: option.name,
        normalized_name: option.name.toLowerCase().trim(),
        scope: scope,
        owner_user_id: scope === 'private' ? 1 : null, // TODO: Get actual user ID
        color: option.color,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }

      createTagMutation.mutate(
        {
          name: option.name,
          scope: scope,
          color: option.color,
        },
        {
          onSuccess: (createdTag) => {
            onTagsChange([...selectedTags, createdTag])
            if (onTagCreate) {
              onTagCreate(createdTag)
            }
            setQuery('')
            setNewTagName('')
            setIsCreating(false)
            setShowDropdown(false)
          },
        }
      )
    } else {
      // Select existing tag
      const tag: Tag = {
        id: option.id,
        name: option.name,
        normalized_name: option.name.toLowerCase().trim(),
        scope: option.isGlobal ? 'global' : 'private',
        owner_user_id: option.isPrivate ? 1 : null, // TODO: Get actual user ID
        color: option.color,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }

      if (!selectedTags.some(t => t.id === tag.id)) {
        onTagsChange([...selectedTags, tag])
      }
      setQuery('')
      setNewTagName('')
      setIsCreating(false)
      setShowDropdown(false)
    }
  }

  // Handle tag removal
  const handleTagRemove = (tagToRemove: Tag) => {
    onTagsChange(selectedTags.filter(tag => tag.id !== tagToRemove.id))
  }

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(event.target as Node)
      ) {
        setShowDropdown(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Focus input when dropdown opens
  useEffect(() => {
    if (showDropdown && inputRef.current) {
      inputRef.current.focus()
    }
  }, [showDropdown])

  return (
    <div className={`relative ${className}`}>
      {/* Selected tags */}
      {selectedTags.length > 0 && (
        <div className="flex flex-wrap gap-1 p-2 border border-gray-300 rounded-t-lg">
          {selectedTags.map((tag) => (
            <div key={tag.id} className="relative">
              <TagChip tag={tag} />
              <button
                className="ml-1 text-gray-500 hover:text-gray-700"
                onClick={() => handleTagRemove(tag)}
              >
                <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fillRule="evenodd"
                    d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                    clipRule="evenodd"
                  />
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleChange}
          onFocus={handleFocus}
          placeholder={placeholder}
          disabled={disabled}
          className={`
            w-full px-3 py-2 border ${
              selectedTags.length > 0 ? 'border-t-0 border-b-0' : 'border'
            } border-gray-300 rounded-b-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
            ${disabled ? 'bg-gray-100 cursor-not-allowed' : 'bg-white'}
          `}
        />

        {/* Dropdown */}
        {showDropdown && query && (
          <div
            ref={dropdownRef}
            className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-y-auto"
          >
            {isSearching && (
              <div className="px-3 py-2 text-sm text-gray-500">Searching...</div>
            )}
            
            {!isSearching && availableOptions.length === 0 && (
              <div className="px-3 py-2 text-sm text-gray-500">No tags found</div>
            )}

            {!isSearching && availableOptions.length > 0 && (
              <div className="py-1">
                {availableOptions.map((option) => (
                  <button
                    key={option.id}
                    className="w-full px-3 py-2 text-left text-sm hover:bg-gray-100 flex items-center gap-2"
                    onClick={() => handleOptionSelect(option)}
                  >
                    <div
                      className="w-3 h-3 rounded-full flex-shrink-0"
                      style={{ backgroundColor: option.color }}
                    />
                    <span className="truncate">{option.name}</span>
                    {option.isNew && (
                      <span className="ml-auto text-xs text-green-600 font-medium">
                        Create
                      </span>
                    )}
                    {option.isGlobal && !option.isNew && (
                      <span className="ml-auto text-xs text-gray-500">
                        Global
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}

            {showNearMatches && isLoadingNearMatches && (
              <div className="px-3 py-2 text-sm text-gray-500">Checking suggestions...</div>
            )}

            {showNearMatches && !isLoadingNearMatches && nearMatches && nearMatches.length > 0 && (
              <div className="border-t border-gray-200 pt-2 mt-2">
                <div className="px-3 py-2 text-xs font-medium text-gray-500 mb-1">
                  Similar tags exist:
                </div>
                {nearMatches.map((match) => (
                  <button
                    key={match.tag.id}
                    className="w-full px-3 py-2 text-left text-sm hover:bg-gray-100 flex items-center gap-2"
                    onClick={() => handleOptionSelect({
                      id: match.tag.id,
                      name: match.tag.name,
                      color: match.tag.color,
                      isGlobal: match.tag.scope === 'global',
                      isPrivate: match.tag.scope === 'private',
                    })}
                  >
                    <div
                      className="w-3 h-3 rounded-full flex-shrink-0"
                      style={{ backgroundColor: match.tag.color }}
                    />
                    <span className="truncate">{match.tag.name}</span>
                    <span className="ml-auto text-xs text-gray-500">
                      {match.distance === 0 ? 'Exact match' : `Similar`}
                    </span>
                  </button>
                ))}
              </div>
            )}

            {nameAvailability && !nameAvailability.available && (
              <div className="border-t border-gray-200 pt-2 mt-2">
                <div className="px-3 py-2 text-xs text-red-600">
                  A tag with this name already exists
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {maxTags && selectedTags.length >= maxTags && (
        <div className="text-xs text-gray-500 mt-1">
          Maximum {maxTags} tags allowed
        </div>
      )}
    </div>
  )
}