import { useCollections } from '../contexts/CollectionContext'

interface CollectionToolbarProps {
  showNewLabel?: boolean
  className?: string
  onNewCollection?: () => void
}

export default function CollectionToolbar({ showNewLabel = true, className = '', onNewCollection }: CollectionToolbarProps) {
  const { collections, activeCollectionId, setActiveCollectionId, isLoading } = useCollections()

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
            className="shrink-0 px-3 py-1.5 glass-button text-[10px] font-black uppercase tracking-wider whitespace-nowrap"
            aria-label="Create new collection"
          >
            + New Collection
          </button>
        )}
      </div>
    </div>
  )
}
