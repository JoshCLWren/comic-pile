import React, { useState, useEffect } from 'react'
import Modal from '../Modal'
import type { Tag } from '../../types'
import { useTag, useTagUsage, useUpdateTag, useDeleteTag } from '../../hooks/useTags'
import { TAG_COLOR_NAMES, TAG_COLOR_PALETTE } from '../../utils/tagColors'

interface TagManagementDialogProps {
  tag: Tag | null
  isOpen: boolean
  onClose: () => void
  onTagUpdate?: (tag: Tag) => void
  onTagDelete?: (tagId: number) => void
}

/**
 * Rename, recolor, or delete a tag.
 *
 * The color grid uses the same fixed 32-color palette the API validates against.
 * Deletion is confirmed with the tag's current assignment count so the blast
 * radius is explicit before a cascading delete runs.
 */
export function TagManagementDialog({
  tag,
  isOpen,
  onClose,
  onTagUpdate,
  onTagDelete,
}: TagManagementDialogProps) {
  const [name, setName] = useState('')
  const [color, setColor] = useState<string>('')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: tagData, isLoading: isLoadingTag } = useTag(tag?.id ?? 0)
  const { data: usageInfo, isLoading: isLoadingUsage } = useTagUsage(tag?.id ?? 0)

  const updateTagMutation = useUpdateTag()
  const deleteTagMutation = useDeleteTag()

  useEffect(() => {
    if (tagData) {
      setName(tagData.name)
      setColor(tagData.color)
    }
  }, [tagData])

  useEffect(() => {
    if (!isOpen) {
      setShowDeleteConfirm(false)
      setError(null)
    }
  }, [isOpen])

  const isFormValid =
    Boolean(tagData) &&
    name.trim() !== '' &&
    (name !== tagData?.name || color !== tagData?.color)

  const handleUpdate = async () => {
    if (!tagData) {
      return
    }

    try {
      const updatedTag = await updateTagMutation.mutateAsync({
        id: tagData.id,
        request: { name: name.trim(), color },
      })
      onTagUpdate?.(updatedTag)
      onClose()
    } catch {
      setError('Those tag changes could not be saved.')
    }
  }

  const handleDelete = async () => {
    if (!tagData) {
      return
    }

    try {
      await deleteTagMutation.mutateAsync(tagData.id)
      onTagDelete?.(tagData.id)
      setShowDeleteConfirm(false)
      onClose()
    } catch {
      setError('That tag could not be deleted.')
    }
  }

  if (!tagData) {
    return (
      <Modal isOpen={isOpen} onClose={onClose} title="Tag Management">
        <div className="py-4 text-center text-sm text-stone-400">
          {isLoadingTag ? 'Loading tag...' : 'Tag not found'}
        </div>
      </Modal>
    )
  }

  const assignmentCount = usageInfo?.total_assignments ?? 0

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`Manage Tag - ${tagData.name}`}
    >
      <div className="space-y-4 md:space-y-6">
        <section>
          <h3 className="mb-2 text-sm font-bold text-stone-400">Tag Information</h3>
          <dl className="space-y-1 text-sm text-stone-300">
            <div className="flex gap-2">
              <dt className="text-stone-500">Type</dt>
              <dd className="font-semibold text-stone-100">{tagData.scope}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-stone-500">Assignments</dt>
              <dd className="font-semibold text-stone-100">
                {isLoadingUsage ? 'Loading...' : assignmentCount}
              </dd>
            </div>
          </dl>
        </section>

        <section>
          <h3 className="mb-2 text-sm font-bold text-stone-400">Edit Tag</h3>

          <div className="space-y-2">
            <label htmlFor="tag-name" className="block text-sm font-semibold text-stone-300">
              Tag Name
            </label>
            <input
              id="tag-name"
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="form-control w-full rounded-lg px-3 py-2 text-sm"
              placeholder="Enter tag name"
            />
          </div>

          <div className="mt-4 space-y-2">
            <span className="block text-sm font-semibold text-stone-300">Color</span>
            <div className="grid grid-cols-8 gap-2">
              {TAG_COLOR_NAMES.map((paletteName) => (
                <button
                  key={paletteName}
                  type="button"
                  aria-label={paletteName}
                  aria-pressed={color === TAG_COLOR_PALETTE[paletteName]}
                  title={paletteName}
                  className={`h-8 w-8 rounded-lg border-2 transition-colors ${
                    color === TAG_COLOR_PALETTE[paletteName]
                      ? 'border-stone-200'
                      : 'border-transparent hover:border-stone-500'
                  }`}
                  style={{ backgroundColor: TAG_COLOR_PALETTE[paletteName] }}
                  onClick={() => setColor(TAG_COLOR_PALETTE[paletteName])}
                />
              ))}
            </div>
          </div>
        </section>

        <section className="border-t border-[var(--theme-border)] pt-4">
          <h3 className="mb-2 text-sm font-bold text-[var(--theme-danger)]">Danger Zone</h3>

          {!showDeleteConfirm ? (
            <button
              type="button"
              onClick={() => setShowDeleteConfirm(true)}
              className="w-full rounded-lg bg-[var(--theme-danger)] px-4 py-2 text-white hover:bg-[var(--theme-danger-hover)] transition-colors"
            >
              Delete Tag
            </button>
          ) : (
            <div className="space-y-3">
              <div className="surface-panel p-3 border-[var(--theme-danger)]">
                <p className="text-sm text-stone-200">
                  Delete this tag? This also removes its assignments and cannot be undone.
                </p>
                <p className="mt-1 text-sm text-stone-300">
                  {`This tag is currently used by ${assignmentCount} ${
                    assignmentCount === 1 ? 'item' : 'items'
                  }.`}
                </p>
              </div>

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setShowDeleteConfirm(false)}
                  className="flex-1 rounded-lg border border-[var(--theme-border)] px-4 py-2 text-stone-300 hover:bg-white/5 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={deleteTagMutation.isPending}
                  className="flex-1 rounded-lg bg-[var(--theme-danger)] px-4 py-2 text-white hover:bg-[var(--theme-danger-hover)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {deleteTagMutation.isPending ? 'Deleting...' : 'Delete Tag'}
                </button>
              </div>
            </div>
          )}
        </section>

        {error && (
          <p className="text-sm text-[var(--theme-danger)]" role="alert">
            {error}
          </p>
        )}

        <div className="flex gap-2 border-t border-[var(--theme-border)] pt-4">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 rounded-lg border border-[var(--theme-border)] px-4 py-2 text-stone-300 hover:bg-white/5 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleUpdate}
            disabled={!isFormValid || updateTagMutation.isPending}
            className="flex-1 rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-white hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {updateTagMutation.isPending ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </Modal>
  )
}