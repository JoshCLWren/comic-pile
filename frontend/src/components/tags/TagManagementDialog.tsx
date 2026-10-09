import React, { useState, useEffect } from 'react'
import Modal from '../Modal'
import { TagInput } from './TagInput'
import type { Tag, TagAssignment, TagUsageInfo } from '../../types'
import { useTag, useTagUsage, useUpdateTag, useDeleteTag } from '../../hooks/useTags'

interface TagManagementDialogProps {
  tag: Tag | null
  isOpen: boolean
  onClose: () => void
  onTagUpdate?: (tag: Tag) => void
  onTagDelete?: (tagId: number) => void
}

interface TagFormData {
  name: string
  color: string
}

const COLOR_PALETTE = [
  '#DC2626', // red
  '#EA580C', // orange
  '#D97706', // amber
  '#CA8A04', // yellow
  '#65A30D', // lime
  '#16A34A', // green
  '#059669', // emerald
  '#0891B2', // teal
  '#0284C7', // sky
  '#2563EB', // blue
  '#4F46E5', // indigo
  '#7C3AED', // violet
  '#9333EA', // purple
  '#A21CAF', // fuchsia
  '#DB2777', // pink
  '#E11D48', // rose
  // Add all 32 colors from the backend
]

export function TagManagementDialog({
  tag,
  isOpen,
  onClose,
  onTagUpdate,
  onTagDelete,
}: TagManagementDialogProps) {
  const [formData, setFormData] = useState<TagFormData>({
    name: '',
    color: COLOR_PALETTE[0],
  })
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)

  // Get tag data and usage info
  const { data: tagData, isLoading: isLoadingTag } = useTag(tag?.id || 0)
  const { data: usageInfo, isLoading: isLoadingUsage } = useTagUsage(tag?.id || 0)

  // Update tag mutation
  const updateTagMutation = useUpdateTag()
  const deleteTagMutation = useDeleteTag()

  // Initialize form when tag changes
  useEffect(() => {
    if (tagData) {
      setFormData({
        name: tagData.name,
        color: tagData.color,
      })
    }
  }, [tagData])

  // Handle form input changes
  const handleInputChange = (field: keyof TagFormData, value: string) => {
    setFormData(prev => ({ ...prev, [field]: value }))
  }

  // Handle color selection
  const handleColorSelect = (color: string) => {
    setFormData(prev => ({ ...prev, color }))
  }

  // Handle tag update
  const handleUpdate = async () => {
    if (!tagData) return

    try {
      const updatedTag = await updateTagMutation.mutateAsync({
        id: tagData.id,
        request: {
          name: formData.name,
          color: formData.color,
        },
      })

      if (onTagUpdate) {
        onTagUpdate(updatedTag)
      }
      onClose()
    } catch (error) {
      console.error('Failed to update tag:', error)
    }
  }

  // Handle tag delete
  const handleDelete = async () => {
    if (!tagData) return

    try {
      setIsDeleting(true)
      await deleteTagMutation.mutateAsync(tagData.id)

      if (onTagDelete) {
        onTagDelete(tagData.id)
      }
      onClose()
      setShowDeleteConfirm(false)
    } catch (error) {
      console.error('Failed to delete tag:', error)
      setIsDeleting(false)
    }
  }

  if (!tagData) {
    return (
      <Modal isOpen={isOpen} onClose={onClose} title="Tag Management">
        <div className="p-6">
          {isLoadingTag ? (
            <div className="text-center py-4">Loading tag...</div>
          ) : (
            <div className="text-center py-4">Tag not found</div>
          )}
        </div>
      </Modal>
    )
  }

  // Check if form is valid
  const isFormValid = formData.name.trim() !== '' && 
                     (formData.name !== tagData.name || formData.color !== tagData.color)

  return (
    <Modal 
      isOpen={isOpen} 
      onClose={onClose} 
      title={`Manage Tag - ${tagData.name}`}
    >
      <div className="p-6 space-y-6">
        {/* Tag Information */}
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-gray-700">Tag Information</h3>
          <div className="text-sm text-gray-600 space-y-1">
            <div>Type: <span className="font-medium">{tagData.scope}</span></div>
            <div>ID: <span className="font-medium">{tagData.id}</span></div>
            <div>Created: <span className="font-medium">{new Date(tagData.created_at).toLocaleDateString()}</span></div>
            <div>Updated: <span className="font-medium">{new Date(tagData.updated_at).toLocaleDateString()}</span></div>
          </div>
        </div>

        {/* Usage Information */}
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-gray-700">Usage</h3>
          {isLoadingUsage ? (
            <div className="text-sm text-gray-500">Loading usage information...</div>
          ) : (
            <div className="text-sm text-gray-600 space-y-1">
              <div>Assignments: <span className="font-medium">{usageInfo?.assignment_count || 0}</span></div>
              <div>Filter references: <span className="font-medium">{usageInfo?.filter_references || 0}</span></div>
            </div>
          )}
        </div>

        {/* Edit Form */}
        <div className="space-y-4">
          <h3 className="text-sm font-medium text-gray-700">Edit Tag</h3>
          
          {/* Name Input */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Tag Name
            </label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => handleInputChange('name', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Enter tag name"
            />
          </div>

          {/* Color Picker */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Color
            </label>
            <div className="grid grid-cols-8 gap-2">
              {COLOR_PALETTE.map((color) => (
                <button
                  key={color}
                  className={`w-8 h-8 rounded-lg border-2 ${
                    formData.color === color ? 'border-gray-900' : 'border-gray-300'
                  } hover:border-gray-500`}
                  style={{ backgroundColor: color }}
                  onClick={() => handleColorSelect(color)}
                  title={color}
                />
              ))}
            </div>
          </div>
        </div>

        {/* Delete Section */}
        <div className="space-y-4 border-t pt-4">
          <h3 className="text-sm font-medium text-red-700">Danger Zone</h3>
          
          {!showDeleteConfirm ? (
            <button
              onClick={() => setShowDeleteConfirm(true)}
              className="w-full px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500"
            >
              Delete Tag
            </button>
          ) : (
            <div className="space-y-3">
              <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
                <p className="text-sm text-red-800">
                  Are you sure you want to delete this tag? This action cannot be undone.
                </p>
                {usageInfo && (usageInfo.assignment_count > 0 || usageInfo.filter_references > 0) && (
                  <div className="mt-2 text-sm text-red-700">
                    <p>This tag is currently used in {usageInfo.assignment_count} assignments and {usageInfo.filter_references} filters.</p>
                  </div>
                )}
              </div>
              
              <div className="flex gap-2">
                <button
                  onClick={() => setShowDeleteConfirm(false)}
                  className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDelete}
                  disabled={isDeleting}
                  className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isDeleting ? 'Deleting...' : 'Delete Tag'}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-2 pt-4 border-t">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleUpdate}
            disabled={!isFormValid || updateTagMutation.isPending}
            className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {updateTagMutation.isPending ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </Modal>
  )
}