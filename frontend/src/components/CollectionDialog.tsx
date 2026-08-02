import type { Collection } from '../types'

interface CollectionDialogProps {
  collection?: Collection | null
  onClose: () => void
}

/**
 * Collections were removed in #636. This compatibility shell prevents old
 * callers from rendering collection create/edit controls while those callers
 * are deleted in follow-up slices.
 */
export default function CollectionDialog(_props: CollectionDialogProps) {
  return null
}
