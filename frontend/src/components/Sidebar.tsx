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
  } = useCollections()
  const [isDialogOpen, setIsDialogOpen] = useState(false)

  const handleCreateClick = () => {
    setIsDialogOpen(true)
  }

  const handleCloseDialog = () => {
    setIsDialogOpen(false)
  }

  const handleSelectCollection = (id: number | null) => {
    setActiveCollectionId(id)
  }

  const handleDeleteCollection = async (id: number, event: React.MouseEvent) => {
    event.stopPropagation()
    if (window.confirm('Are you sure you want to delete this collection?')) {
      await deleteCollection(id)
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

        {isLoading ? (
          <div className="sidebar__loading">Loading...</div>
        ) : (
          <ul className="sidebar__list">
            <li
              className={`sidebar__item ${activeCollectionId === null ? 'sidebar__item--active' : ''}`}
              onClick={() => handleSelectCollection(null)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  handleSelectCollection(null)
                }
              }}
            >
              <span className="sidebar__item-name">All Collections</span>
            </li>
            {collections.map((collection) => (
              <li
                key={collection.id}
                className={`sidebar__item ${activeCollectionId === collection.id ? 'sidebar__item--active' : ''}`}
                onClick={() => handleSelectCollection(collection.id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    handleSelectCollection(collection.id)
                  }
                }}
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
