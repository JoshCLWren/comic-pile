import { useCollections } from '../contexts/CollectionContext'
import { collectionsEnabled } from '../config/featureFlags'

/**
 * Props for the CollectionToolbar component.
 */
interface CollectionToolbarProps {
  /** Whether to show the "New Collection" label on the button */
  showNewLabel?: boolean
  /** Additional CSS classes to apply to the toolbar */
  className?: string
  /** Callback function when the "New Collection" button is clicked */
  onNewCollection?: () => void
}

/**
 * CollectionToolbar component.
 * Displays a dropdown for selecting collections and a button to create new collections.
 * Shows loading state while fetching collections and error state if fetching fails.
 */
export default function CollectionToolbar({ showNewLabel = true, className = '', onNewCollection }: CollectionToolbarProps) {
  const { collections, activeCollectionId, setActiveCollectionId, isLoading, error } = useCollections()

  if (!collectionsEnabled) {
    return null
  }

  const handleCollectionChange = (collectionId: number | null) => {
    setActiveCollectionId(collectionId)
  }

  if (isLoading) {
    return (
      <div className={`collection-toolbar ${className}`}>
        <div className="text-[10px] text-stone-500 uppercase tracking-wider">Loading collections...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className={`collection-toolbar ${className}`}>
        <div className="text-[10px] text-red-400 uppercase tracking-wider" role="alert">
          Error: {error.message}
        </div>
      </div>
    )
  }

  return (
    <div className={`collection-toolbar flex items-center gap-2 ${className}`}>
      <div className="flex items-center gap-2 flex-1">
        <select
          value={activeCollectionId ?? 'all'}
          onChange={(e) => handleCollectionChange(e.target.value === 'all' ? null : Number(e.target.value))}
          className="min-w-0 w-full max-w-[280px] bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-[10px] font-black uppercase tracking-wider text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-600/40"
          aria-label="Filter by collection"
        >
          <option value="all">All Collections</option>
          {collections.map((collection) => (
            <option key={collection.id} value={collection.id}>
              {collection.name}
              {collection.is_default ? ' ★' : ''}
            </option>
          ))}
        </select>
        {showNewLabel && onNewCollection && (
          <button
            type="button"
            onClick={onNewCollection}
            className="shrink-0 px-3 py-1.5 glass-button text-[10px] font-black uppercase tracking-wider whitespace-nowrap min-h-[44px]"
            aria-label="Create new collection"
          >
            Create new collection
          </button>
        )}
      </div>
    </div>
  )
}
