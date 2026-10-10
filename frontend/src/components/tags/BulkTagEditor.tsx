import React, { useState, useMemo } from 'react'
import Modal from '../Modal'
import { TagInput } from './TagInput'
import type { Tag } from '../../types'
import { useBulkTagOperations } from '../../hooks/useTags'
import { toTagTargetType, type TagCacheKeyType } from '../../utils/tagTargetType'

interface BulkTagEditorProps {
  selectedItems: Array<{
    id: number
    type: TagCacheKeyType
    name: string
  }>
  isOpen: boolean
  onClose: () => void
  onOperationComplete?: () => void
}

type BulkAction = 'add' | 'remove'

const ACTION_LABELS: Record<BulkAction, string> = {
  add: 'Add',
  remove: 'Remove',
}

/**
 * Bulk add/remove of one or more tags across many selected targets.
 *
 * Only the chosen tag assignment changes: the API applies each operation as a
 * single assignment or unassignment per target, so unrelated tags on those
 * issues are preserved.
 */
export function BulkTagEditor({
  selectedItems,
  isOpen,
  onClose,
  onOperationComplete,
}: BulkTagEditorProps) {
  const [selectedTags, setSelectedTags] = useState<Tag[]>([])
  const [action, setAction] = useState<BulkAction>('add')
  const [showConfirm, setShowConfirm] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const bulkTagMutation = useBulkTagOperations()

  const targetType = selectedItems.length > 0 ? toTagTargetType(selectedItems[0].type) : null
  const summary = useMemo(
    () => ({
      itemCount: selectedItems.length,
      tagCount: selectedTags.length,
      actionText: action === 'add' ? 'adding' : 'removing',
      totalOperations: selectedItems.length * selectedTags.length,
    }),
    [action, selectedItems.length, selectedTags.length],
  )

  const resetState = () => {
    setSelectedTags([])
    setAction('add')
    setShowConfirm(false)
    setError(null)
  }

  const handleClose = () => {
    resetState()
    onClose()
  }

  const handlePerformBulkOperation = async () => {
    if (!targetType || selectedTags.length === 0) {
      return
    }

    const operations = selectedTags.map((tag) => ({
      tag_id: tag.id,
      target_type: targetType,
      target_ids: selectedItems.map((item) => item.id),
      action,
    }))

    try {
      await bulkTagMutation.mutateAsync(operations)
      resetState()
      onOperationComplete?.()
      onClose()
    } catch {
      setError('Those tag changes could not be applied. Please try again.')
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={`Bulk Tag Editor (${selectedItems.length} items selected)`}
    >
      <div className="space-y-4 md:space-y-6">
        <section>
          <h3 className="mb-2 text-sm font-bold text-stone-400">Selected Items</h3>
          <ul className="max-h-32 space-y-1 overflow-y-auto">
            {selectedItems.map((item, index) => (
              <li key={`${item.type}-${item.id}`} className="flex items-center gap-2 text-sm text-stone-300">
                <span className="text-stone-500">[{index + 1}]</span>
                <span className="font-semibold text-stone-100">{item.name}</span>
                <span className="text-stone-500">({item.type})</span>
              </li>
            ))}
          </ul>
        </section>

        <section role="radiogroup" aria-label="Bulk tag action">
          <h3 className="mb-2 text-sm font-bold text-stone-400">Action</h3>
          <div className="flex gap-2">
            {(['add', 'remove'] as const).map((option) => (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={action === option}
                onClick={() => {
                  setAction(option)
                  setError(null)
                }}
                className={`flex-1 rounded-lg border px-4 py-2 transition-colors ${
                  action === option
                    ? 'border-[var(--theme-primary-action)] bg-[var(--theme-primary-action)] text-white'
                    : 'border-[var(--theme-border)] text-stone-300 hover:bg-white/5'
                }`}
              >
                {ACTION_LABELS[option]} Tags
              </button>
            ))}
          </div>
        </section>

        <section>
          <h3 className="mb-2 text-sm font-bold text-stone-400">{ACTION_LABELS[action]} Tags</h3>
          <TagInput
            selectedTags={selectedTags}
            onTagsChange={setSelectedTags}
            placeholder={`Select tags to ${action}...`}
            maxTags={10}
            className="w-full"
          />
        </section>

        {selectedTags.length > 0 && (
          <section>
            <h3 className="mb-2 text-sm font-bold text-stone-400">Summary</h3>
            <div className="surface-panel space-y-1 p-3 text-sm text-stone-300">
              <p>{`${summary.itemCount} items will be updated`}</p>
              <p>{`${summary.tagCount} tags will be ${summary.actionText}`}</p>
              <p>{`${summary.totalOperations} total operations`}</p>
              <p className="text-xs text-stone-500">
                Other tags on these items are left unchanged.
              </p>
            </div>
          </section>
        )}

        {showConfirm && (
          <section className="surface-panel p-4 border-[var(--theme-warning)]">
            <h4 className="mb-1 text-sm font-bold text-stone-100">Confirm Bulk Operation</h4>
            <p className="text-sm text-stone-300">
              This will {action} {summary.tagCount}{' '}
              {summary.tagCount === 1 ? 'tag' : 'tags'} across {summary.itemCount}{' '}
              {summary.itemCount === 1 ? 'item' : 'items'}.
            </p>

            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={() => setShowConfirm(false)}
                className="flex-1 rounded-lg border border-[var(--theme-border)] px-4 py-2 text-stone-300 hover:bg-white/5 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handlePerformBulkOperation}
                disabled={bulkTagMutation.isPending}
                className="flex-1 rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-white hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {bulkTagMutation.isPending ? 'Processing...' : 'Confirm'}
              </button>
            </div>
          </section>
        )}

        {error && (
          <p className="text-sm text-[var(--theme-danger)]" role="alert">
            {error}
          </p>
        )}

        <div className="flex gap-2 border-t border-[var(--theme-border)] pt-4">
          <button
            type="button"
            onClick={handleClose}
            className="flex-1 rounded-lg border border-[var(--theme-border)] px-4 py-2 text-stone-300 hover:bg-white/5 transition-colors"
          >
            {selectedTags.length > 0 ? 'Cancel' : 'Close'}
          </button>

          {selectedTags.length > 0 && !showConfirm && (
            <button
              type="button"
              onClick={() => setShowConfirm(true)}
              className="flex-1 rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-white hover:bg-[var(--theme-primary-action-hover)] transition-colors"
            >
              {ACTION_LABELS[action]} Tags
            </button>
          )}
        </div>
      </div>
    </Modal>
  )
}