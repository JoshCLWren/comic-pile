import { useState } from 'react'
import { useEffectiveTags, useUnassignTag } from '../../hooks/useTags'
import type { TagTargetType } from '../../services/api-tags'
import { TagChips } from './TagChips'
import { TagEditor } from './TagEditor'
import { tagErrorMessage } from './tagErrors'
import { useAdminFlag } from './useAdminFlag'

export interface TagSectionProps {
  targetType: TagTargetType
  targetId: number
  /** Human-readable label for the target, e.g. a thread title. */
  targetLabel: string
  /** True when the viewer is an admin (global tags are admin-managed). */
  isAdmin?: boolean
  /** Eyebrow label for the section. */
  title?: string
}

/**
 * Tags block for issue, thread, Reading Plan, and Roll views (issue #3032).
 *
 * Shows direct + inherited chips with source navigation and an edit affordance
 * that opens the inline editor without navigating away. The block is
 * content-sized and wraps, so it never destabilizes dense layouts like Roll.
 */
export function TagSection({
  targetType,
  targetId,
  targetLabel,
  isAdmin,
  title = 'Tags',
}: TagSectionProps) {
  const [editorOpen, setEditorOpen] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const effective = useEffectiveTags(targetType, targetId)
  const unassign = useUnassignTag()
  const contextIsAdmin = useAdminFlag()
  const canManageGlobals = isAdmin ?? contextIsAdmin

  return (
    <div className="min-w-0 space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-black uppercase tracking-widest text-[var(--theme-text-muted)]">
          {title}
        </span>
        <button
          type="button"
          onClick={() => {
            setFailure(null)
            setEditorOpen(true)
          }}
          className="rounded-lg border border-[var(--theme-border)] px-2.5 py-1 text-xs font-bold text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
        >
          Edit tags
        </button>
      </div>
      {failure && (
        <p role="alert" className="text-xs font-semibold text-[var(--theme-danger)]">
          {failure}
        </p>
      )}
      <TagChips
        data={effective.data}
        isPending={effective.isPending}
        isError={effective.isError}
        canEdit
        canRemoveTag={(tag) => tag.scope === 'private' || canManageGlobals}
        onRemoveDirect={(tag) => {
          setFailure(null)
          void unassign
            .mutateAsync({
              id: tag.id,
              data: { target_type: targetType, target_id: targetId },
            })
            .catch((error: unknown) => {
              setFailure(tagErrorMessage(error, `Could not remove “${tag.name}”.`))
            })
        }}
        onRetry={() => void effective.refetch()}
      />
      <TagEditor
        targetType={targetType}
        targetId={targetId}
        targetLabel={targetLabel}
        isOpen={editorOpen}
        onClose={() => setEditorOpen(false)}
        isAdmin={canManageGlobals}
      />
    </div>
  )
}
