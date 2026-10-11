import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { EffectiveTag } from '../services/api-tags'

export interface TagChipsProps {
  data: { target_type: string; target_id: number; direct_tags: any[]; effective_tags: EffectTag[] }
  canEdit?: boolean
  canRemoveTag?: (tag: EffectTag['tag']) => boolean
  onRemoveDirect?: (tag: EffectTag['tag']) => void
}

export function sourceRoute(target: { target_type: string; target_id: number; display_name: string }) {
  switch (target.target_type) {
    case 'Thread':
      return `/thread/${target.target_id}`
    case 'ContinuityPlan':
      return `/continuity-plans/${target.target_id}`
    default:
      return '#'
  }
}

export function TagChips({ data, canEdit, canRemoveTag, onRemoveDirect }: TagChipsProps) {
  const [showSources, setShowSources] = useState<Set<number>>(new Set())

  function toggleSources(id: number) {
    setShowSources((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <section aria-label="Tags">
      <ul className="flex flex-wrap max-w-full">
        {data.effective_tags.map((elem, idx) => {
          const tag = elem.tag
          const isInherited = !elem.direct
          const sourcesKey = idx
          return (
            <li key={idx} className="inline-flex items-center mr-2 mb-1">
              <span>{tag.name}</span>
              {isInherited && (
                <>
                  <span className="px-1">Inherited</span>
                  <button
                    type="button"
                    aria-label={`show sources for inherited tag ${tag.name}`}
                    onClick={() => toggleSources(sourcesKey)}
                    className="ml-1"
                  >
                    ▼
                  </button>
                  {showSources.has(sourcesKey) && (
                    <ul role="list" aria-label={`sources for ${tag.name}`} className="ml-2">
                      {elem.sources.map((src, i) => (
                        <li key={i}>
                          <Link to={sourceRoute(src)}>{src.display_name}</Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
              {canEdit && canRemoveTag && canRemoveTag(tag) && (
                <button
                  type="button"
                  aria-label={`Remove tag ${tag.name}`}
                  onClick={() => onRemoveDirect?.(tag)}
                  className="ml-1"
                >
                  ✕
                </button>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
