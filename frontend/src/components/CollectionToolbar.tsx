interface CollectionToolbarProps {
  showNewLabel?: boolean
  className?: string
  onNewCollection?: () => void
}

/**
 * Collections were removed in #636. Keep a temporary null component while
 * Roll and Queue are simplified in follow-up slices.
 */
export default function CollectionToolbar(_props: CollectionToolbarProps) {
  return null
}
