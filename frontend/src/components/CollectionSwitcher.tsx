import { useCollections } from '../contexts/CollectionContext'
import './CollectionSwitcher.css'

/**
 * Collection Switcher component that displays a dropdown to select
 * the active collection for filtering content.
 *
 * @returns {JSX.Element} The collection switcher dropdown
 */
export default function CollectionSwitcher() {
  const { collections, activeCollectionId, setActiveCollectionId, isLoading } = useCollections()

  const handleChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value
    setActiveCollectionId(value === 'all' ? null : parseInt(value, 10))
  }

  if (isLoading) {
    return (
      <div className="collection-switcher">
        <label htmlFor="collection-select" className="collection-switcher__label">
          Collection
        </label>
        <div className="collection-switcher__loading">Loading...</div>
      </div>
    )
  }

  return (
    <div className="collection-switcher">
      <label htmlFor="collection-select" className="collection-switcher__label">
        Collection
      </label>
      <select
        id="collection-select"
        value={activeCollectionId ?? 'all'}
        onChange={handleChange}
        className="collection-switcher__select"
        aria-label="Select collection"
      >
        <option value="all">All Collections</option>
        {collections.map((collection) => (
          <option key={collection.id} value={collection.id}>
            {collection.name}
            {collection.is_default ? ' ★' : ''}
          </option>
        ))}
      </select>
    </div>
  )
}
