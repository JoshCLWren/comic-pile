import { useCollections } from '../../contexts/CollectionContext'
import { collectionsEnabled } from '../../config/featureFlags'

export function CollectionBadge({ collectionId }: { collectionId: number }) {
  const { collections } = useCollections()
  const collection = collections.find(c => c.id === collectionId)

  if (!collectionsEnabled) {
    return null
  }

  if (!collection) return null

  return (
    <span data-testid="collection-badge" className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-500/20 text-amber-300 border border-amber-500/30">
      {collection.name}
    </span>
  )
}
