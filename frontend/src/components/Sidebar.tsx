import { useState } from 'react'
import { useCollections } from '../contexts/CollectionContext'
import CollectionDialog from './CollectionDialog'
import './Sidebar.css'

/**
 * Sidebar component that displays collection management UI.
 * Shows a list of collections with the ability to create, select,
 * and delete collections.
 *
 * @returns {JSX.Element} The sidebar component
 */
export default function Sidebar() {
  const {
    collections,
    activeCollectionId,
    setActiveCollectionId,
    deleteCollection,
    isLoading,
    error,
    retry,
  } = useCollections()
  const [isDialogOpen, setIsDialogOpen] = useState(false)

  const handleCreateClick = () => {
    setIsDialogOpen(true)
  }

  const handleCloseDialog = () => {
    setIsDialogOpen(false)
  }

  const handleDeleteCollection = async (id: number, event: React.MouseEvent) => {
    event.stopPropagation()
    if (window.confirm('Are you sure you want to delete this collection?')) {
      try {
        await deleteCollection(id)
      } catch {
        alert('Failed to delete collection. Please try again.')
      }
    }
  }

  return (
    <aside className="sidebar">
      <div className="sidebar__section">
        <div className="sidebar__header">
          <h3 className="sidebar__title">Collections</h3>
          <button
            type="button"
            onClick={handleCreateClick}
            className="sidebar__add-btn"
            aria-label="Create new collection"
            title="Create new collection"
          >
            +
          </button>
        </div>

        {isLoading && (
          <div className="sidebar__loading">
            <div className="sidebar__spinner" aria-label="Loading collections" />
            <span>Loading collections...</span>
          </div>
        )}

        {error && !isLoading && (
          <div className="sidebar__error">
            <div className="sidebar__error-message">
              {error.status === 401
                ? 'Please log in to view collections'
                : error.message || 'Failed to load collections'}
            </div>
            <button
              type="button"
              onClick={retry}
              className="sidebar__retry-btn"
              aria-label="Retry loading collections"
            >
              Retry
            </button>
          </div>
        )}

        {!isLoading && !error && (
          <ul className="sidebar__list">
            <li className={`sidebar__item ${activeCollectionId === null ? 'sidebar__item--active' : ''}`}>
              <button
                className="sidebar__item-btn"
                onClick={() => setActiveCollectionId(null)}
                type="button"
              >
                <span className="sidebar__item-name">All Collections</span>
              </button>
            </li>
            {collections.map((collection) => (
              <li
                key={collection.id}
                className={`sidebar__item ${activeCollectionId === collection.id ? 'sidebar__item--active' : ''}`}
              >
                <button
                  className="sidebar__item-btn"
                  onClick={() => setActiveCollectionId(collection.id)}
                  type="button"
                >
                  <span className="sidebar__item-name">
                    {collection.name}
                    {collection.is_default && (
                      <span className="sidebar__default-marker" aria-label="Default collection">
                        {' '}
                        ★
                      </span>
                    )}
                  </span>
                </button>
                {!collection.is_default && (
                  <button
                    type="button"
                    onClick={(e) => handleDeleteCollection(collection.id, e)}
                    className="sidebar__delete-btn"
                    aria-label={`Delete ${collection.name} collection`}
                    title="Delete collection"
                  >
                    ×
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {isDialogOpen && <CollectionDialog onClose={handleCloseDialog} />}
    </aside>
  )
}
