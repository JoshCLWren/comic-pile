import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { TagChip } from './TagChip'
import { TagInput } from './TagInput'
import { TagManagementDialog } from './TagManagementDialog'
import type { Tag, TagInheritanceSource } from '../../types'
import type { TagCacheKeyType } from '../../utils/tagTargetType'
import { toTagTargetType } from '../../utils/tagTargetType'
import {
  useAssignTag,
  useEffectiveTags,
  useUnassignTag,
} from '../../hooks/useTags'

interface TagEditorProps {
  /** Which taggable kind this editor is editing. */
  targetType: TagCacheKeyType
  targetId: number
  /** Human label for this object, used as the inheritance-source name. */
  targetLabel: string
  /** Hides the editor when the viewer may not assign tags here. */
  canEdit?: boolean
  className?: string
}

const SOURCE_ROUTES: Record<string, (id: number) => string> = {
  Issue: (id) => `/thread/${id}`,
  Thread: (id) => `/thread/${id}`,
  ContinuityPlan: (id) => `/continuity-plans/${id}`,
}

/**
 * Read and edit the tags on one issue, thread, or Reading Plan.
 *
 * Only a tag this object assigns directly can be removed here; inherited tags
 * are read-only and link to the object that contributes them, which is what
 * keeps "removing one source" from misleadingly implying the tag disappeared.
 */
export function TagEditor({
  targetType,
  targetId,
  targetLabel,
  canEdit = true,
  className = '',
}: TagEditorProps) {
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)
  const [manageTag, setManageTag] = useState<Tag | null>(null)

  const { data: effective, isPending, isError } = useEffectiveTags(targetType, targetId)
  const assignTagMutation = useAssignTag()
  const unassignTagMutation = useUnassignTag()

  const directTags = effective?.direct_tags ?? []
  const inheritedTags = (effective?.effective_tags ?? []).filter((entry) => !entry.direct)

  const handleRemove = (tag: Tag) => {
    unassignTagMutation.mutate({
      tagId: tag.id,
      request: { target_type: toTagTargetType(targetType), target_id: targetId },
    })
  }

  const handleAdd = (tags: Tag[]) => {
    const assignedIds = new Set(directTags.map((tag) => tag.id))
    for (const tag of tags) {
      if (assignedIds.has(tag.id)) {
        continue
      }
      assignTagMutation.mutate({
        tag,
        targetLabel,
        request: { target_type: toTagTargetType(targetType), target_id: targetId },
      })
    }
    setEditing(false)
  }

  const goToSource = (source: TagInheritanceSource) => {
    const route = SOURCE_ROUTES[source.target_type]
    if (!route) {
      return
    }
    setEditing(false)
    navigate(route(source.target_id))
  }

  if (isPending) {
    return <p className={`text-xs text-stone-500 ${className}`}>Loading tags...</p>
  }

  if (isError) {
    return (
      <p className={`text-xs text-[var(--theme-danger)] ${className}`} role="alert">
        Unable to load tags.
      </p>
    )
  }

  return (
    <div className={`space-y-2 ${className}`} data-tag-editor={targetType}>
      <span className="text-xs font-black uppercase tracking-widest text-stone-500">Tags</span>

      {directTags.length === 0 && inheritedTags.length === 0 && !editing ? (
        <p className="text-xs text-stone-500">No tags yet</p>
      ) : (
        <div className="flex flex-wrap items-center gap-1">
          {directTags.map((tag) => (
            <span key={tag.id} className="inline-flex items-center">
              <TagChip tag={tag} onTagClick={() => setManageTag(tag)} />
              {canEdit && (
                <button
                  type="button"
                  aria-label={`Remove ${tag.name}`}
                  className="ml-1 text-stone-500 hover:text-stone-200 transition-colors"
                  onClick={() => handleRemove(tag)}
                >
                  <svg
                    className="w-3 h-3"
                    fill="currentColor"
                    viewBox="0 0 20 20"
                    aria-hidden="true"
                  >
                    <path
                      fillRule="evenodd"
                      d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293-4.293a1 1 0 01-1.414 1.414L10 11.414l4.293-4.293a1 1 0 010-1.414z"
                      clipRule="evenodd"
                    />
                  </svg>
                </button>
              )}
            </span>
          ))}

          {inheritedTags.map((entry) => (
            <TagChip
              key={entry.tag.id}
              tag={entry.tag}
              isInherited
              inheritanceSources={entry.sources}
              onSourceClick={goToSource}
            />
          ))}
        </div>
      )}

      {canEdit && !editing && (
        <button
          type="button"
          className="text-xs font-semibold text-[var(--theme-comic-accent)] hover:underline"
          onClick={() => setEditing(true)}
        >
          Edit tags
        </button>
      )}

      {editing && (
        <TagInput
          selectedTags={directTags}
          onTagsChange={handleAdd}
          placeholder="Add tags..."
          className="w-full"
        />
      )}

      {(assignTagMutation.isError || unassignTagMutation.isError) && (
        <p className="text-xs text-[var(--theme-danger)]" role="alert">
          Those tag changes could not be saved.
        </p>
      )}

      <TagManagementDialog
        tag={manageTag}
        isOpen={Boolean(manageTag)}
        onClose={() => setManageTag(null)}
      />
    </div>
  )
}

/**
 * Read-only tag display for a list row, where editing would not fit.
 */
export function TagListRow({ targetType, targetId }: { targetType: TagCacheKeyType; targetId: number }) {
  const { data: effective } = useEffectiveTags(targetType, targetId)

  if (!effective || effective.effective_tags.length === 0) {
    return null
  }

  return (
    <span className="inline-flex items-center gap-1" data-tag-row={targetType}>
      {effective.effective_tags.map((entry) => (
        <TagChip key={entry.tag.id} tag={entry.tag} isInherited={!entry.direct} />
      ))}
    </span>
  )
}