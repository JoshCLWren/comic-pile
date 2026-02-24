import { useState, useEffect } from 'react'
import { useCollections, type Collection, type CollectionCreate, type CollectionUpdate } from '../contexts/CollectionContext'
import './CollectionDialog.css'

interface CollectionDialogProps {
  collection?: Collection | null
  onClose: () => void
}

/**
 * Dialog component for creating or editing a collection.
 *
 * @param {CollectionDialogProps} props - Component props
 * @returns {JSX.Element | null} The dialog or null when closed
 */
export default function CollectionDialog({ collection, onClose }: CollectionDialogProps) {
  const { createCollection, updateCollection } = useCollections()
  const isEditMode = !!collection

  const [name, setName] = useState('')
  const [isDefault, setIsDefault] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    if (collection) {
      setName(collection.name)
      setIsDefault(collection.is_default)
    } else {
      setName('')
      setIsDefault(false)
    }
    setError(null)
  }, [collection])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!name.trim()) {
      setError('Collection name is required')
      return
    }

    if (name.length > 100) {
      setError('Collection name must be 100 characters or less')
      return
    }

    setIsSubmitting(true)

    try {
      if (isEditMode && collection) {
        const updateData: CollectionUpdate = {
          name: name.trim(),
          is_default: isDefault,
        }
        await updateCollection(collection.id, updateData)
      } else {
        const createData: CollectionCreate = {
          name: name.trim(),
          is_default: isDefault,
        }
        await createCollection(createData)
      }
      onClose()
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'An unexpected error occurred'
      setError(errorMessage)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose()
    }
  }

  return (
    <div className="collection-dialog__overlay" onClick={handleBackdropClick}>
      <div className="collection-dialog">
        <div className="collection-dialog__header">
          <h2 className="collection-dialog__title">
            {isEditMode ? 'Edit Collection' : 'Create Collection'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="collection-dialog__close-btn"
            aria-label="Close dialog"
          >
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit} className="collection-dialog__form">
          <div className="collection-dialog__field">
            <label htmlFor="collection-name" className="collection-dialog__label">
              Collection Name <span className="collection-dialog__required">*</span>
            </label>
            <input
              id="collection-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={100}
              placeholder="Enter collection name"
              className="collection-dialog__input"
              autoFocus
            />
            <span className="collection-dialog__char-count">{name.length}/100</span>
          </div>

          <div className="collection-dialog__field collection-dialog__checkbox-field">
            <label className="collection-dialog__checkbox-label">
              <input
                type="checkbox"
                checked={isDefault}
                onChange={(e) => setIsDefault(e.target.checked)}
                className="collection-dialog__checkbox"
              />
              <span className="collection-dialog__checkbox-text">
                Make this my default collection
              </span>
            </label>
          </div>

          {error && (
            <div className="collection-dialog__error" role="alert">
              {error}
            </div>
          )}

          <div className="collection-dialog__actions">
            <button
              type="button"
              onClick={onClose}
              className="collection-dialog__btn collection-dialog__btn--secondary"
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="collection-dialog__btn collection-dialog__btn--primary"
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Saving...' : isEditMode ? 'Update' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
