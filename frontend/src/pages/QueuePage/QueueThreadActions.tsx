interface QueueThreadActionsProps {
  title: string
  snoozeIcon: string
  snoozeLabel: string
  onRead: () => void
  onEdit: () => void
  onSnooze: () => void
  onDelete: () => void
}

export default function QueueThreadActions({
  title,
  snoozeIcon,
  snoozeLabel,
  onRead,
  onEdit,
  onSnooze,
  onDelete,
}: QueueThreadActionsProps) {
  const stopCardClick = (action: () => void) => (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    action()
  }

  return (
    <div
      className="pl-8 md:pl-[2.75rem] flex flex-wrap gap-2"
      role="group"
      aria-label={`Actions for ${title}`}
    >
      <button
        type="button"
        onClick={stopCardClick(onRead)}
        className="px-3 py-2 rounded-lg bg-amber-600/20 text-amber-300 text-xs font-bold hover:bg-amber-600/30"
      >
        📖 Read
      </button>
      <button
        type="button"
        onClick={stopCardClick(onEdit)}
        className="px-3 py-2 rounded-lg bg-white/5 text-stone-300 text-xs font-bold hover:bg-white/10"
      >
        ✏️ Edit
      </button>
      <button
        type="button"
        onClick={stopCardClick(onSnooze)}
        className="px-3 py-2 rounded-lg bg-teal-600/15 text-teal-300 text-xs font-bold hover:bg-teal-600/25"
      >
        {snoozeIcon} {snoozeLabel}
      </button>
      <button
        type="button"
        onClick={stopCardClick(onDelete)}
        className="px-3 py-2 rounded-lg bg-red-600/15 text-red-300 text-xs font-bold hover:bg-red-600/25"
      >
        🗑 Delete
      </button>
    </div>
  )
}
