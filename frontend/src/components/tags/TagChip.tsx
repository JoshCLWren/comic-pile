import React from 'react'
import type { Tag, TagInheritanceSource } from '../../types'

interface TagChipProps {
  tag: Tag
  isInherited?: boolean
  inheritanceSources?: TagInheritanceSource[]
  onTagClick?: (tag: Tag) => void
  onSourceClick?: (source: TagInheritanceSource) => void
  className?: string
}

const TAG_COLORS = {
  red: '#DC2626',
  orange: '#EA580C',
  amber: '#D97706',
  yellow: '#CA8A04',
  lime: '#65A30D',
  green: '#16A34A',
  emerald: '#059669',
  teal: '#0891B2',
  cyan: '#0891B2',
  sky: '#0284C7',
  blue: '#2563EB',
  indigo: '#4F46E5',
  violet: '#7C3AED',
  purple: '#9333EA',
  fuchsia: '#A21CAF',
  pink: '#DB2777',
  rose: '#E11D48',
  // Add all 32 colors from the backend palette
  // For now, using a subset for brevity
}

export function TagChip({
  tag,
  isInherited = false,
  inheritanceSources = [],
  onTagClick,
  onSourceClick,
  className = '',
}: TagChipProps) {
  const handleClick = () => {
    if (onTagClick) {
      onTagClick(tag)
    }
  }

  const handleSourceClick = (source: TagInheritanceSource) => {
    if (onSourceClick) {
      onSourceClick(source)
    }
  }

  const backgroundColor = TAG_COLORS[tag.color as keyof typeof TAG_COLORS] || tag.color
  const textColor = tag.color === 'yellow' || tag.color === 'lime' || tag.color === 'amber' 
    ? 'text-gray-900' 
    : 'text-white'

  return (
    <div
      className={`
        inline-flex items-center gap-1 px-2 py-1 rounded-full text-sm font-medium
        cursor-pointer transition-all duration-200 hover:scale-105 hover:shadow-md
        ${isInherited ? 'opacity-75 border border-gray-300' : ''}
        ${textColor}
        ${className}
      `}
      style={{ backgroundColor }}
      onClick={handleClick}
    >
      <span className="truncate">{tag.name}</span>
      
      {isInherited && inheritanceSources.length > 0 && (
        <div className="relative group">
          <svg 
            className="w-3 h-3 ml-1 flex-shrink-0" 
            fill="currentColor" 
            viewBox="0 0 20 20"
          >
            <path 
              fillRule="evenodd" 
              d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" 
              clipRule="evenodd" 
            />
          </svg>
          
          {/* Inheritance sources tooltip */}
          <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 w-48 p-2 bg-white border border-gray-200 rounded-lg shadow-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-10">
            <div className="text-xs font-medium text-gray-700 mb-1">Inherited from:</div>
            <div className="space-y-1">
              {inheritanceSources.map((source, index) => (
                <button
                  key={source.id}
                  className="block w-full text-left text-xs text-blue-600 hover:text-blue-800 hover:underline"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleSourceClick(source)
                  }}
                >
                  {source.type}: {source.name}
                </button>
              ))}
            </div>
            <div className="absolute top-full left-1/2 transform -translate-x-1/2 -mt-1">
              <div className="w-2 h-2 bg-white border-r border-b border-gray-200 transform rotate-45"></div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

interface TagListProps {
  tags: Tag[]
  isInherited?: boolean
  inheritanceSources?: TagInheritanceSource[]
  onTagClick?: (tag: Tag) => void
  onSourceClick?: (source: TagInheritanceSource) => void
  className?: string
  maxTags?: number
}

export function TagList({
  tags,
  isInherited = false,
  inheritanceSources = [],
  onTagClick,
  onSourceClick,
  className = '',
  maxTags,
}: TagListProps) {
  const displayTags = maxTags ? tags.slice(0, maxTags) : tags
  const remainingTags = maxTags && tags.length > maxTags ? tags.slice(maxTags) : []

  return (
    <div className={`flex flex-wrap gap-1 ${className}`}>
      {displayTags.map((tag) => (
        <TagChip
          key={tag.id}
          tag={tag}
          isInherited={isInherited}
          inheritanceSources={inheritanceSources}
          onTagClick={onTagClick}
          onSourceClick={onSourceClick}
        />
      ))}
      
      {remainingTags.length > 0 && (
        <div className="inline-flex items-center px-2 py-1 rounded-full text-sm font-medium bg-gray-100 text-gray-600">
          +{remainingTags.length} more
        </div>
      )}
    </div>
  )
}