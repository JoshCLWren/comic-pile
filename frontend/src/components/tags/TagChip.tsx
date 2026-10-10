import React from 'react'
import type { Tag, TagInheritanceSource } from '../../types'
import { TAG_COLOR_PALETTE } from '../../utils/tagColors'

interface TagChipProps {
  tag: Tag
  isInherited?: boolean
  inheritanceSources?: TagInheritanceSource[]
  onTagClick?: (tag: Tag) => void
  onSourceClick?: (source: TagInheritanceSource) => void
  className?: string
}

/**
 * One tag pill.
 *
 * Direct and inherited tags are distinguishable without relying on color alone:
 * an inherited chip renders at reduced opacity with a dashed outline. The chip
 * background comes from the server-validated fixed palette, which is a genuine
 * local data encoding rather than a semantic theme role.
 */
export function TagChip({
  tag,
  isInherited = false,
  inheritanceSources = [],
  onTagClick,
  onSourceClick,
  className = '',
}: TagChipProps) {
  const interactive = Boolean(onTagClick)
  const backgroundColor = TAG_COLOR_PALETTE[tag.color] ?? tag.color
  const textClass = tagNeedsDarkText(backgroundColor) ? 'text-stone-900' : 'text-white'

  const handleActivate = () => {
    onTagClick?.(tag)
  }

  return (
    <span
      className={[
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold',
        interactive ? 'cursor-pointer hover:brightness-110 transition-[filter]' : '',
        isInherited ? 'opacity-70 ring-1 ring-inset ring-current/40 border border-dashed' : '',
        textClass,
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      style={{ backgroundColor }}
      onClick={interactive ? handleActivate : undefined}
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onKeyDown={
        interactive
          ? (event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                handleActivate()
              }
            }
          : undefined
      }
      data-tag-id={tag.id}
      data-inherited={isInherited ? 'true' : undefined}
    >
      <span className="truncate">{tag.name}</span>

      {isInherited && inheritanceSources.length > 0 && (
        <span className="relative group inline-flex">
          <svg
            className="w-3 h-3 flex-shrink-0"
            fill="currentColor"
            viewBox="0 0 20 20"
            aria-hidden="true"
          >
            <path
              fillRule="evenodd"
              d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
              clipRule="evenodd"
            />
          </svg>

          <span className="sr-only">Inherited from:</span>

          <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-56 p-2 surface-panel shadow-lg opacity-0 invisible group-hover:opacity-100 group-focus-within:opacity-100 group-hover:visible group-focus-within:visible transition-opacity z-10">
            {inheritanceSources.map((source) => (
              <button
                key={`${source.target_type}-${source.target_id}`}
                type="button"
                className="block w-full text-left text-xs text-stone-300 hover:text-stone-100 hover:underline py-0.5"
                onClick={(event) => {
                  event.stopPropagation()
                  onSourceClick?.(source)
                }}
              >
                {source.display_name}
              </button>
            ))}
          </span>
        </span>
      )}
    </span>
  )
}

/**
 * Pick readable text for a palette background.
 *
 * The palette is fixed and server-validated, so the set of possible background
 * colors is known. Luminance is measured against the actual hex so the decision
 * stays correct if the palette gains a lighter entry later.
 *
 * @param backgroundColor - The chip background color.
 * @returns Whether dark foreground text is required.
 */
function tagNeedsDarkText(backgroundColor: string): boolean {
  const hex = backgroundColor.replace('#', '')
  if (hex.length !== 6) {
    return false
  }

  const red = parseInt(hex.slice(0, 2), 16)
  const green = parseInt(hex.slice(2, 4), 16)
  const blue = parseInt(hex.slice(4, 6), 16)

  if (Number.isNaN(red) || Number.isNaN(green) || Number.isNaN(blue)) {
    return false
  }

  const luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
  return luminance > 0.6
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

/**
 * A wrapping row of tag chips.
 *
 * Renders nothing at all for an empty list so optional tag UI leaves no empty
 * flex track behind in the layout.
 */
export function TagList({
  tags,
  isInherited = false,
  inheritanceSources = [],
  onTagClick,
  onSourceClick,
  className = '',
  maxTags,
}: TagListProps) {
  if (tags.length === 0) {
    return null
  }

  const displayTags = maxTags ? tags.slice(0, maxTags) : tags
  const remainingCount = maxTags ? Math.max(0, tags.length - displayTags.length) : 0

  return (
    <div className={`flex flex-wrap items-center gap-1 ${className}`}>
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

      {remainingCount > 0 && (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-stone-800 text-stone-300">
          +{remainingCount} more
        </span>
      )}
    </div>
  )
}