import React, { useState, useMemo } from 'react'
import Modal from '../Modal'
import { TagInput } from './TagInput'
import { TagList } from './TagChip'
import type { Tag } from '../../types'
import { useBulkTagOperations } from '../../hooks/useTags'
import { toTagTargetType, type TagCacheKeyType } from '../../utils/tagTargetType'

interface BulkTagEditorProps {
  selectedItems: Array<{
    id: number
    type: 'issue' | 'thread' | 'plan'
    name: string
  }>
  isOpen: boolean
  onClose: () => void
  onOperationComplete?: () => void
}

interface BulkOperation {
  tag_id: number
  target_type: 'Issue' | 'Thread' | 'ContinuityPlan'
  target_ids: number[]
  action: 'add' | 'remove'
}

const ACTION_LABELS = {
  add: 'Add',
  remove: 'Remove',
} as const

export function BulkTagEditor({
  selectedItems,
  isOpen,
  onClose,
  onOperationComplete,
}: BulkTagEditorProps) {
  const [selectedTags, setSelectedTags] = useState<Tag[]>([])
  const [action, setAction] = useState<'add' | 'remove'>('add')
  const [showConfirm, setShowConfirm] = useState(false)

  // Bulk operations mutation
  const bulkTagMutation = useBulkTagOperations()

  // Generate bulk operations
  const bulkOperations: BulkOperation[] = useMemo(() => {
    if (!selectedTags.length) return []

    const firstItemType = (selectedItems[0]?.type || 'issue') as TagCacheKeyType
    const targetType = toTagTargetType(firstItemType)

    return selectedTags.map(tag => ({
      tag_id: tag.id,
      target_type: targetType,
      target_ids: selectedItems.map(item => item.id),
      action,
    }))
  }, [selectedTags, selectedItems, action])

  // Handle perform bulk operation
  const handlePerformBulkOperation = async () => {
    try {
      await bulkTagMutation.mutateAsync(bulkOperations)
      setShowConfirm(false)
      setSelectedTags([])
      setAction('add')
      if (onOperationComplete) {
        onOperationComplete()
      }
      onClose()
    } catch (error) {
      console.error('Failed to perform bulk operation:', error)
    }
  }

  // Calculate summary
  const summary = useMemo(() => {
    const itemCount = selectedItems.length
    const tagCount = selectedTags.length
    const actionText = action === 'add' ? 'adding' : 'removing'

    return {
      itemCount,
      tagCount,
      actionText,
      totalOperations: itemCount * tagCount,
    }
  }, [selectedItems, selectedTags, action])

  // Reset state when modal closes
  const handleClose = () => {
    setSelectedTags([])
    setAction('add')
    setShowConfirm(false)
    onClose()
  }

  return (
    <Modal 
      isOpen={isOpen} 
      onClose={handleClose} 
      title={`Bulk Tag Editor (${selectedItems.length} items selected)`}
    >
      <div className="p-6 space-y-6">
        {/* Selected Items */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-700">Selected Items</h3>
          <div className="max-h-32 overflow-y-auto space-y-1">
            {selectedItems.map((item, index) => (
              <div key={item.id} className="text-sm text-gray-600 flex items-center gap-2">
                <span className="text-gray-400">[{index + 1}]</span>
                <span className="font-medium">{item.name}</span>
                <span className="text-gray-400">({item.type})</span>
              </div>
            ))}
          </div>
        </div>

        {/* Action Selection */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-700">Action</h3>
          <div className="flex gap-2">
            <button
              onClick={() => setAction('add')}
              className={`flex-1 px-4 py-2 rounded-lg border ${
                action === 'add' 
                  ? 'border-blue-500 bg-blue-50 text-blue-700' 
                  : 'border-gray-300 text-gray-700 hover:bg-gray-50'
              }`}
            >
              {ACTION_LABELS.add} Tags
            </button>
            <button
              onClick={() => setAction('remove')}
              className={`flex-1 px-4 py-2 rounded-lg border ${
                action === 'remove' 
                  ? 'border-red-500 bg-red-50 text-red-700' 
                  : 'border-gray-300 text-gray-700 hover:bg-gray-50'
              }`}
            >
              {ACTION_LABELS.remove} Tags
            </button>
          </div>
        </div>

        {/* Tag Selection */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-700">
            {ACTION_LABELS[action]} Tags
          </h3>
          <TagInput
            selectedTags={selectedTags}
            onTagsChange={setSelectedTags}
            placeholder={`Select tags to ${action}...`}
            maxTags={10}
            className="w-full"
          />
        </div>

        {/* Summary */}
        {selectedTags.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-sm font-medium text-gray-700">Summary</h3>
            <div className="p-3 bg-gray-50 border border-gray-200 rounded-lg">
              <div className="text-sm text-gray-600 space-y-1">
                <div>
                  <span className="font-medium">{summary.itemCount}</span> items will be updated
                </div>
                <div>
                  <span className="font-medium">{summary.tagCount}</span> tags will be {summary.actionText}
                </div>
                <div>
                  <span className="font-medium">{summary.totalOperations}</span> total operations
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Confirm Dialog */}
        {showConfirm && (
          <div className="space-y-3">
            <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
              <h4 className="text-sm font-medium text-yellow-800 mb-2">Confirm Bulk Operation</h4>
              <p className="text-sm text-yellow-700">
                This will {action} {selectedTags.length} tag(s) from {selectedItems.length} selected item(s). 
                This action cannot be undone.
              </p>
            </div>
            
            <div className="flex gap-2">
              <button
                onClick={() => setShowConfirm(false)}
                className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handlePerformBulkOperation}
                disabled={bulkTagMutation.isPending}
                className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {bulkTagMutation.isPending ? 'Processing...' : 'Confirm'}
              </button>
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 pt-4 border-t">
          <button
            onClick={handleClose}
            className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
          >
            {selectedTags.length > 0 ? 'Cancel' : 'Close'}
          </button>
          
          {selectedTags.length > 0 && !showConfirm && (
            <button
              onClick={() => setShowConfirm(true)}
              className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              {ACTION_LABELS[action]} Tags
            </button>
          )}
        </div>
      </div>
    </Modal>
  )
}