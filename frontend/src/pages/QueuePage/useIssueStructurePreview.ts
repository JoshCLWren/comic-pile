import { useCallback, useState } from 'react'
import type { Issue } from '../../types'
import type { IssueEditPreviewResponse } from '../../services/api-issues'
import { getApiErrorDetail } from '../../utils/apiError'

/** A structural edit awaiting a before/after preview (#4654). */
export type StructuralEdit =
  | { type: 'delete'; issueId: number }
  | {
      type: 'reorder'
      nextIssues: Issue[]
      announcement?: string
      focusTarget?: { issueId: number; direction: 'up' | 'down' }
    }

/**
 * Queues delete/reorder edits only after their exact projected before/after
 * rows have been reviewed (#4654). The backend performs the projection in a
 * rolled-back savepoint, so a cancelled preview leaves every row untouched.
 */
export function useIssueStructurePreview({
  threadId,
  deferred,
  previewDelete,
  previewReorder,
  onDelete,
  onReorder,
  onError,
}: {
  threadId: number
  deferred: boolean
  previewDelete?: (threadId: number, issueId: number) => Promise<IssueEditPreviewResponse>
  previewReorder?: (threadId: number, issueIds: number[]) => Promise<IssueEditPreviewResponse>
  onDelete: (issueId: number) => void
  onReorder: (
    nextIssues: Issue[],
    options?: {
      announcement?: string
      focusTarget?: { issueId: number; direction: 'up' | 'down' }
    },
  ) => void
  onError: (message: string) => void
}) {
  const [preview, setPreview] = useState<{
    edit: StructuralEdit
    response: IssueEditPreviewResponse
  } | null>(null)
  const [isPreviewing, setIsPreviewing] = useState(false)

  const commit = useCallback((edit: StructuralEdit) => {
    if (edit.type === 'delete') {
      onDelete(edit.issueId)
      return
    }
    onReorder(edit.nextIssues, {
      announcement: edit.announcement,
      focusTarget: edit.focusTarget,
    })
  }, [onDelete, onReorder])

  const request = useCallback(async (edit: StructuralEdit) => {
    // Immediate mode has no Save boundary and keeps its historical direct path.
    if (!deferred) {
      commit(edit)
      return
    }
    if (edit.type === 'delete') {
      const previewFn = previewDelete
      if (!previewFn) {
        commit(edit)
        return
      }
      setIsPreviewing(true)
      try {
        const response = await previewFn(threadId, edit.issueId)
        setPreview({ edit, response })
      } catch (err: unknown) {
        console.error('[IssueToggleList] Error previewing structural edit:', err)
        onError(getApiErrorDetail(err))
      } finally {
        setIsPreviewing(false)
      }
      return
    }
    const previewFn = previewReorder
    if (!previewFn) {
      commit(edit)
      return
    }
    const issueIds = edit.nextIssues.map((issue) => issue.id)
    setIsPreviewing(true)
    try {
      const response = await previewFn(threadId, issueIds)
      setPreview({ edit, response })
    } catch (err: unknown) {
      console.error('[IssueToggleList] Error previewing structural edit:', err)
      onError(getApiErrorDetail(err))
    } finally {
      setIsPreviewing(false)
    }
  }, [commit, deferred, onError, previewDelete, previewReorder, threadId])

  const cancel = useCallback(() => setPreview(null), [])

  const confirm = useCallback(() => {
    if (!preview) return
    commit(preview.edit)
    setPreview(null)
  }, [commit, preview])

  return { preview, isPreviewing, request, cancel, confirm }
}
